import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import get_settings
from src.db.base import Base

# Import models so SQLAlchemy can discover metadata.
from src.db.models.order import Order, OrderStatusHistory  # noqa: F401
from src.db.models.user import User  # noqa: F401
from src.db.session import engine

logger = logging.getLogger(__name__)


async def init_db(async_engine: AsyncEngine | None = None) -> None:
    settings = get_settings()
    if not settings.auto_create_schema:
        return

    resolved_engine = async_engine or engine

    # Step 1: Create all missing tables from SQLAlchemy metadata
    async with resolved_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Step 2: Heal existing tables on PostgreSQL
    # Each ALTER runs in its own connection so one failure doesn't roll back others.
    _dsn = settings.resolved_database_dsn
    if "sqlite" in _dsn:
        logger.info("SQLite detected — skipping schema healing (not needed)")
        return

    logger.info("Running PostgreSQL schema healing...")
    await _heal_users_table(resolved_engine)
    await _heal_orders_table(resolved_engine)
    await _heal_order_status_history_table(resolved_engine)
    logger.info("Schema healing complete.")


async def _run_safe_sql(engine_: AsyncEngine, statements: list[str]) -> None:
    """Execute each SQL statement in its own connection. Failures are logged and skipped."""
    from sqlalchemy import text

    for sql in statements:
        try:
            async with engine_.begin() as conn:
                await conn.execute(text(sql))
        except Exception as exc:
            logger.debug("Heal SQL skipped (OK if already applied): %s — %s", sql[:80], exc)


async def _heal_users_table(engine_: AsyncEngine) -> None:
    await _run_safe_sql(engine_, [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_master BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        # Drop NOT NULL for columns that might be null during user creation
        "ALTER TABLE users ALTER COLUMN phone DROP NOT NULL",
        "ALTER TABLE users ALTER COLUMN full_name DROP NOT NULL",
        "ALTER TABLE users ALTER COLUMN language DROP NOT NULL",
    ])


async def _heal_orders_table(engine_: AsyncEngine) -> None:
    await _run_safe_sql(engine_, [
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_id INTEGER",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS issue_type VARCHAR(32)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS issue_label VARCHAR(100)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS phone VARCHAR(32)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS latitude FLOAT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS longitude FLOAT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS status VARCHAR(32)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS assigned_dispatcher_telegram_id BIGINT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS assigned_master_telegram_id BIGINT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS final_amount NUMERIC(12, 2)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(255)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS rating INTEGER",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
    ])


async def _heal_order_status_history_table(engine_: AsyncEngine) -> None:
    await _run_safe_sql(engine_, [
        "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS order_id INTEGER",
        "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS from_status VARCHAR(32)",
        "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS to_status VARCHAR(32)",
        "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS actor_telegram_id BIGINT",
        "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
    ])
