import asyncio
import logging
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.handlers.admin import router as admin_router
from src.bot.handlers.client_feedback import router as client_feedback_router
from src.bot.handlers.dispatcher_orders import router as dispatcher_orders_router
from src.bot.handlers.driver_quick_order import router as driver_quick_order_router
from src.bot.handlers.errors import router as errors_router
from src.bot.handlers.master_orders import router as master_orders_router
from src.bot.middlewares.throttling import ThrottlingMiddleware
from src.bot.middlewares.typing import TypingMiddleware
from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.startup import wait_for_dependencies
from src.db.init_db import init_db

settings = get_settings()
logger = logging.getLogger(__name__)


def setup_dispatcher() -> tuple[Dispatcher, object]:
    """
    Set up the aiogram Dispatcher with storage and all routers.
    
    Redis storage is optional — falls back to MemoryStorage automatically
    when USE_REDIS=false or when Redis is unavailable.
    """
    redis_client = None
    storage: object

    if settings.use_redis and settings.redis_dsn:
        try:
            from redis.asyncio import Redis
            from aiogram.fsm.storage.redis import RedisStorage

            redis_client = Redis.from_url(settings.redis_dsn)
            storage = RedisStorage(redis=redis_client)
            logger.info("Using Redis FSM storage: %s", settings.redis_dsn)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — falling back to MemoryStorage.", exc)
            storage = MemoryStorage()
    else:
        storage = MemoryStorage()
        logger.info("Using in-memory FSM storage (USE_REDIS=false).")

    dp = Dispatcher(storage=storage)

    # ── Middlewares ──────────────────────────────────────────────────────────
    # Rate-limit: 1.5 s between messages, 0.3 s between callback taps
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.5))
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit=1.5))
    # Shows "typing…" indicator during slow handlers
    dp.message.middleware(TypingMiddleware())

    # ── Routers — ORDER MATTERS ──────────────────────────────────────────────
    # 1. Error handler first — catches all unhandled exceptions from any router below
    dp.include_router(errors_router)

    # 2. Admin/super-admin commands (/admin, /export_orders, etc.)
    dp.include_router(admin_router)

    # 3. Dispatcher commands (/dashboard, /new_orders, assign callbacks)
    dp.include_router(dispatcher_orders_router)

    # 4. Master order management (accept/reject/status/completion flow)
    dp.include_router(master_orders_router)

    # 5. Client order flow (/start, issue → phone → location → confirm)
    dp.include_router(driver_quick_order_router)

    # 6. Client feedback (rating stars + text after completion)
    dp.include_router(client_feedback_router)

    return dp, redis_client


async def run_bot() -> None:
    configure_logging(settings.log_level)

    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set — cannot start. Please configure environment variables.")
        return

    # Wait for DB (and optionally Redis) to be ready
    await wait_for_dependencies(
        redis_dsn=settings.redis_dsn,
        use_redis=settings.use_redis,
        attempts=settings.dependency_wait_attempts,
        delay_seconds=settings.dependency_wait_delay_seconds,
    )

    # Auto-create / heal DB schema
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=None),  # Each handler sets parse_mode explicitly
    )
    dp, redis_client = setup_dispatcher()

    logger.info("🚀 Starting AutoHelp bot polling…")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            # Drop updates that arrived while bot was offline —
            # avoids ghost "technical error" alerts on restart.
            drop_pending_updates=True,
        )
    finally:
        logger.info("Bot is shutting down…")
        await dp.storage.close()
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                pass
        await bot.session.close()


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(run_bot())
        except (KeyboardInterrupt, SystemExit):
            logger.info("Bot stopped by user.")
            break
        except Exception as exc:
            logger.exception("Bot crashed — restarting in 5 s: %s", exc)
            time.sleep(5)
