"""
AutoHelp.uz — Main Entry Point
Initializes the bot, registers handlers, starts scheduler, and runs polling.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from core.config import settings
from core.database import init_db, close_db
from utils.logger import setup_logger

# Handler routers
from bot.handlers.client.start import router as client_start_router
from bot.handlers.client.order import router as client_order_router
from bot.handlers.client.review import router as client_review_router
from bot.handlers.errors import router as error_router
from bot.handlers.dispatcher.orders import router as dispatcher_router
from bot.handlers.master.orders import router as master_router
from bot.handlers.admin.stats import router as admin_router

# Middlewares
from bot.middlewares import DbSessionMiddleware, AuthMiddleware, ThrottlingMiddleware, FastResponseMiddleware

# Background tasks
from tasks.sla_monitor import check_sla_violations
from tasks.backup import run_daily_backup
from tasks.reports import send_daily_report, send_weekly_report


async def create_storage():
    """Create FSM storage — Redis if available, Memory otherwise."""
    if settings.use_redis:
        from aiogram.fsm.storage.redis import RedisStorage
        from core.redis import get_fsm_redis
        fsm_redis = await get_fsm_redis()
        logger.info("✅ Using Redis FSM storage")
        return RedisStorage(redis=fsm_redis)
    else:
        from aiogram.fsm.storage.memory import MemoryStorage
        logger.info("⚠️ Using Memory FSM storage (states lost on restart)")
        return MemoryStorage()


async def on_startup(bot: Bot):
    """Actions to perform on bot startup."""
    logger.info("🚀 AutoHelp.uz Bot is starting up...")

    # Initialize database (create tables)
    await init_db()
    logger.info("✅ Database initialized")

    # Test Redis if configured
    if settings.use_redis:
        from core.redis import get_redis
        redis = await get_redis()
        await redis.ping()
        logger.info("✅ Redis connected")
    else:
        logger.info("⚡ Redis not configured — using memory storage")

    # Notify admins
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "🚀 <b>AutoHelp.uz Bot ishga tushdi!</b>\n\n"
                "Barcha tizimlar tayyor ✅",
                parse_mode="HTML",
            )
        except Exception:
            pass

    logger.info("✅ Startup complete — bot is ready!")


async def on_shutdown(bot: Bot):
    """Actions to perform on bot shutdown."""
    logger.info("🔄 AutoHelp.uz Bot is shutting down...")

    # Notify admins
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "⚠️ <b>AutoHelp.uz Bot o'chmoqda...</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Close connections
    await close_db()
    if settings.use_redis:
        from core.redis import close_redis
        await close_redis()
    logger.info("✅ Shutdown complete")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Configure APScheduler with all background tasks."""
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    # DB keep-alive — every 4 minutes (prevents Neon cold starts)
    from core.database import keep_alive_ping
    scheduler.add_job(
        keep_alive_ping,
        "interval",
        minutes=4,
        id="db_keepalive",
        name="DB Keep-Alive",
        replace_existing=True,
        misfire_grace_time=30,
    )

    # SLA monitoring — every 60 seconds
    scheduler.add_job(
        check_sla_violations,
        "interval",
        seconds=60,
        args=[bot],
        id="sla_monitor",
        name="SLA Monitor",
        replace_existing=True,
        misfire_grace_time=30,
    )

    # Daily backup — 03:00 Tashkent time
    scheduler.add_job(
        run_daily_backup,
        "cron",
        hour=3,
        minute=0,
        args=[bot],
        id="daily_backup",
        name="Daily Backup",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Daily report — 23:55 Tashkent time
    scheduler.add_job(
        send_daily_report,
        "cron",
        hour=23,
        minute=55,
        args=[bot],
        id="daily_report",
        name="Daily Report",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Weekly report — Monday 08:00 Tashkent time
    scheduler.add_job(
        send_weekly_report,
        "cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        args=[bot],
        id="weekly_report",
        name="Weekly Report",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler


async def main():
    """Main application entry point."""
    # Initialize logger
    setup_logger()

    logger.info("=" * 50)
    logger.info("AutoHelp.uz Bot v1.0.0")
    
    # Hide password in logs
    safe_db_url = settings.get_database_url
    if "@" in safe_db_url:
        host_part = safe_db_url.split("@")[1].split("/")[0]
        logger.info(f"Database Host: {host_part}")
    else:
        logger.info(f"Database string: {safe_db_url[:15]}...")
        
    logger.info(f"Redis: {'configured' if settings.use_redis else 'memory mode'}")
    logger.info("=" * 50)

    # Create bot instance
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Create FSM storage (Redis or Memory)
    storage = await create_storage()

    # Create dispatcher
    dp = Dispatcher(storage=storage)

    # Register startup/shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Register middlewares (order matters!)
    # 0. Fast response — instantly answers ALL callbacks (kills visual lag)
    dp.callback_query.middleware(FastResponseMiddleware())

    # 1. Database session — provides session to all handlers
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    # 2. Auth — identifies user role
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # 3. Throttling — rate limiting (only if Redis is available)
    if settings.use_redis:
        dp.message.middleware(ThrottlingMiddleware(rate_limit=0.5))

    # Register routers (order matters — more specific first!)
    dp.include_router(error_router)  # Handles global errors
    dp.include_router(admin_router)
    dp.include_router(dispatcher_router)
    dp.include_router(master_router)
    dp.include_router(client_start_router)
    dp.include_router(client_order_router)
    dp.include_router(client_review_router)

    # Setup background scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("✅ APScheduler started with background tasks")

    # Start polling
    me = await bot.get_me()
    logger.info(f"🤖 Starting long polling for @{me.username}...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "my_chat_member",
            ],
        )
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
