"""
Database initialization and schema healing.

On startup:
1. create_all() — creates any missing tables from SQLAlchemy metadata.
2. Schema healing — safely adds any missing columns to PostgreSQL tables
   (idempotent ALTER TABLE IF NOT EXISTS statements).
   SQLite is skipped — create_all() is sufficient for SQLite.
"""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import get_settings
from src.db.base import Base

# Import all models so SQLAlchemy can discover their metadata
from src.db.models.order import Order, OrderStatusHistory  # noqa: F401
from src.db.models.user import User  # noqa: F401
from src.db.session import engine

logger = logging.getLogger(__name__)


async def init_db(async_engine: AsyncEngine | None = None) -> None:
    settings = get_settings()
    if not settings.auto_create_schema:
        logger.info("AUTO_CREATE_SCHEMA=false — skipping schema init")
        return

    resolved_engine = async_engine or engine

    # Step 1: Create all missing tables from SQLAlchemy metadata
    async with resolved_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("create_all() completed.")

    # Step 2: Heal existing tables
    _dsn = settings.resolved_database_dsn
    if "sqlite" in _dsn:
        logger.info("SQLite detected — running SQLite schema healing…")
        await _heal_sqlite_db(resolved_engine)
        return

    logger.info("Running PostgreSQL schema healing…")
    await _heal_users_table(resolved_engine)
    await _heal_orders_table(resolved_engine)
    await _heal_order_status_history_table(resolved_engine)
    logger.info("Schema healing complete.")


async def _heal_sqlite_db(engine_: AsyncEngine) -> None:
    await _run_safe_sql(
        engine_,
        [
            # Users Table
            "ALTER TABLE users ADD COLUMN is_master BOOLEAN DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT 0",
            "ALTER TABLE users ADD COLUMN created_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN updated_at TIMESTAMP",
            
            # Orders Table
            "ALTER TABLE orders ADD COLUMN client_id INTEGER",
            "ALTER TABLE orders ADD COLUMN issue_type VARCHAR(32)",
            "ALTER TABLE orders ADD COLUMN issue_label VARCHAR(100)",
            "ALTER TABLE orders ADD COLUMN phone VARCHAR(32)",
            "ALTER TABLE orders ADD COLUMN latitude FLOAT",
            "ALTER TABLE orders ADD COLUMN longitude FLOAT",
            "ALTER TABLE orders ADD COLUMN status VARCHAR(32)",
            "ALTER TABLE orders ADD COLUMN assigned_dispatcher_telegram_id BIGINT",
            "ALTER TABLE orders ADD COLUMN assigned_master_telegram_id BIGINT",
            "ALTER TABLE orders ADD COLUMN final_amount NUMERIC(12, 2)",
            "ALTER TABLE orders ADD COLUMN video_file_id VARCHAR(255)",
            "ALTER TABLE orders ADD COLUMN rating INTEGER",
            "ALTER TABLE orders ADD COLUMN feedback_text VARCHAR(1000)",
            "ALTER TABLE orders ADD COLUMN shortcomings VARCHAR(1000)",
            "ALTER TABLE orders ADD COLUMN completed_at TIMESTAMP",
            "ALTER TABLE orders ADD COLUMN created_at TIMESTAMP",
            "ALTER TABLE orders ADD COLUMN updated_at TIMESTAMP",

            # Order Status History Table
            "ALTER TABLE order_status_history ADD COLUMN order_id INTEGER",
            "ALTER TABLE order_status_history ADD COLUMN from_status VARCHAR(32)",
            "ALTER TABLE order_status_history ADD COLUMN to_status VARCHAR(32)",
            "ALTER TABLE order_status_history ADD COLUMN actor_telegram_id BIGINT",
            "ALTER TABLE order_status_history ADD COLUMN created_at TIMESTAMP",
            "ALTER TABLE order_status_history ADD COLUMN updated_at TIMESTAMP",
        ],
    )


async def _run_safe_sql(engine_: AsyncEngine, statements: list[str]) -> None:
    """Execute each SQL statement in its own connection. Failures are logged and skipped."""
    for sql in statements:
        try:
            async with engine_.begin() as conn:
                await conn.execute(text(sql))
        except Exception as exc:
            logger.debug(
                "Heal SQL skipped (OK if already applied): %.80s — %s", sql, exc
            )


async def _heal_users_table(engine_: AsyncEngine) -> None:
    await _run_safe_sql(
        engine_,
        [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_master BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            # Allow nullable for graceful user creation
            "ALTER TABLE users ALTER COLUMN phone DROP NOT NULL",
            "ALTER TABLE users ALTER COLUMN full_name DROP NOT NULL",
            "ALTER TABLE users ALTER COLUMN language DROP NOT NULL",
        ],
    )


async def _heal_orders_table(engine_: AsyncEngine) -> None:
    await _run_safe_sql(
        engine_,
        [
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
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS feedback_text VARCHAR(1000)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shortcomings VARCHAR(1000)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            # Legacy columns from old schema — drop NOT NULL so old rows don't block inserts
            "ALTER TABLE orders ALTER COLUMN order_uid DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN user_id DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN problem_type DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN description DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN car_make DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN car_model DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN car_number DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN amount DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN currency DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN assigned_to_id DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN accepted_at DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN arrived_at DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN rating DROP NOT NULL",
            "ALTER TABLE orders ALTER COLUMN feedback DROP NOT NULL",
        ],
    )


async def _heal_order_status_history_table(engine_: AsyncEngine) -> None:
    await _run_safe_sql(
        engine_,
        [
            "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS order_id INTEGER",
            "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS from_status VARCHAR(32)",
            "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS to_status VARCHAR(32)",
            "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS actor_telegram_id BIGINT",
            "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        ],
    )
