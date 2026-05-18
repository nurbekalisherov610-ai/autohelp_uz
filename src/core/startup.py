import asyncio
import logging

from sqlalchemy import text

from src.db.session import engine

logger = logging.getLogger(__name__)


async def wait_for_dependencies(
    *,
    redis_dsn: str,
    use_redis: bool = True,
    attempts: int = 30,
    delay_seconds: float = 2.0,
) -> None:
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            # Use text() wrapper — required by SQLAlchemy 2.x for raw SQL
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))

            if use_redis:
                from redis.asyncio import Redis
                redis = Redis.from_url(redis_dsn)
                try:
                    await redis.ping()
                finally:
                    await redis.aclose()

            logger.info("Dependencies are ready")
            return
        except Exception as exc:  # pragma: no cover
            last_error = exc
            logger.warning(
                "Dependencies are not ready yet (attempt %s/%s): %s",
                attempt,
                attempts,
                exc,
            )
            await asyncio.sleep(delay_seconds)

    dep_label = "database and redis" if use_redis else "database"
    raise RuntimeError(f"Dependencies not ready ({dep_label})") from last_error
