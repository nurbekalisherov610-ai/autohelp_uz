"""
AutoHelp.uz - Database Connection (Optimized for Neon)
- Uses Neon's pooler endpoint to avoid cold starts
- Keep-alive pings every 4 minutes
- SSL optimized for asyncpg
"""
import ssl

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import settings


def _build_connect_args() -> dict:
    """Build asyncpg SSL args for Neon/cloud databases."""
    if settings.db_ssl:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return {
            "ssl": ssl_ctx,
            "statement_cache_size": 0,   # Required for pgbouncer pooler
            "command_timeout": 10,        # Fail fast instead of hanging
        }
    return {}


# ── Engine with optimized pool settings ───────────────────────────
engine = create_async_engine(
    settings.get_database_url,
    echo=False,
    # Pool settings tuned for Neon serverless
    pool_size=5,
    max_overflow=3,
    pool_pre_ping=True,          # Verify connections before use
    pool_recycle=180,            # Recycle every 3 min (before Neon 5min timeout)
    pool_timeout=10,             # Don't wait more than 10s for a connection
    connect_args=_build_connect_args(),
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


async def get_session() -> AsyncSession:
    """Dependency: async database session."""
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables on startup."""
    # Must import all models before create_all
    import models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def keep_alive_ping():
    """
    Ping the DB to prevent Neon cold starts.
    Called every 4 minutes by APScheduler.
    """
    from sqlalchemy import text
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        pass


async def close_db():
    """Dispose all connections."""
    await engine.dispose()
