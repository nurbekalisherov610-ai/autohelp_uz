import asyncio
import logging
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

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


def setup_dispatcher() -> tuple[Dispatcher, Redis | None]:
    redis_client: Redis | None = None
    if settings.use_redis:
        redis_client = Redis.from_url(settings.redis_dsn)
        storage = RedisStorage(redis=redis_client)
    else:
        storage = MemoryStorage()

    dp = Dispatcher(storage=storage)
    
    # Register middlewares
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.5))
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit=1.5))
    dp.message.middleware(TypingMiddleware())

    # Error handler FIRST so it catches all unhandled exceptions
    dp.include_router(errors_router)

    # Admin and dispatcher handlers (authorized users only)
    dp.include_router(admin_router)
    dp.include_router(dispatcher_orders_router)

    # Master handlers
    dp.include_router(master_orders_router)

    # Client-facing handlers (driver/client flow) — includes /start and /cancel
    dp.include_router(driver_quick_order_router)

    # Feedback (rating buttons)
    dp.include_router(client_feedback_router)

    return dp, redis_client


async def run_bot() -> None:
    configure_logging(settings.log_level)
    
    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set. Please configure environment variables.")
        return

    await wait_for_dependencies(
        redis_dsn=settings.redis_dsn,
        use_redis=settings.use_redis,
        attempts=settings.dependency_wait_attempts,
        delay_seconds=settings.dependency_wait_delay_seconds,
    )
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp, redis_client = setup_dispatcher()

    logger.info("Starting bot polling")
    try:
        # drop_pending_updates=True avoids processing stale button clicks from
        # before the last restart — this prevents ghost "technical error" popups.
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
    finally:
        await dp.storage.close()
        if redis_client is not None:
            await redis_client.aclose()
        await bot.session.close()


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(run_bot())
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as exc:
            logger.exception("Bot crashed, restarting in 5s: %s", exc)
            time.sleep(5)
