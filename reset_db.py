import asyncio
import sys
sys.path.append('d:/autohelp')

from sqlalchemy.ext.asyncio import create_async_engine
from src.core.config import get_settings
from sqlalchemy import text

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        print("Dropping legacy orders table...")
        await conn.execute(text("DROP TABLE IF EXISTS order_status_history CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS orders CASCADE;"))
        print("Tables dropped successfully. The bot will automatically recreate them cleanly on startup.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
