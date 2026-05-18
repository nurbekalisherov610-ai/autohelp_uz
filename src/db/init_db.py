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
        
        # --- AUTO HEALING FOR EXISTING BROKEN SCHEMAS ON RAILWAY ---
        from sqlalchemy import text
        try:
            # Drop NOT NULL constraints if they exist
            await conn.execute(text("ALTER TABLE users ALTER COLUMN phone DROP NOT NULL"))
            await conn.execute(text("ALTER TABLE users ALTER COLUMN full_name DROP NOT NULL"))
            await conn.execute(text("ALTER TABLE users ALTER COLUMN language DROP NOT NULL"))
        except Exception:
            pass  # Ignore if using sqlite or table doesn't exist
            
        try:
            # Ensure is_master exists
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_master BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"))
        except Exception:
            pass
            
        try:
            # Ensure missing orders columns exist
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS issue_type VARCHAR(32)"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS status VARCHAR(32)"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS final_amount NUMERIC(12, 2)"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(255)"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS rating INTEGER"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_id INTEGER"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS phone VARCHAR(32)"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS latitude FLOAT"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS longitude FLOAT"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS issue_label VARCHAR(100)"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS assigned_dispatcher_telegram_id BIGINT"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS assigned_master_telegram_id BIGINT"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"))
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"))
        except Exception:
            pass
            
        try:
            # Ensure missing order_status_history columns exist
            await conn.execute(text("ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS from_status VARCHAR(32)"))
            await conn.execute(text("ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS to_status VARCHAR(32)"))
            await conn.execute(text("ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"))
            await conn.execute(text("ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"))
        except Exception:
            pass
