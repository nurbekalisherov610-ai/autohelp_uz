from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import get_settings
from src.db.base import Base

# Import models so SQLAlchemy can discover metadata.
from src.db.models.order import Order, OrderStatusHistory  # noqa: F401
from src.db.models.user import User  # noqa: F401
from src.db.session import engine


async def init_db(async_engine: AsyncEngine | None = None) -> None:
    settings = get_settings()
    if not settings.auto_create_schema:
        return

    resolved_engine = async_engine or engine
    async with resolved_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
