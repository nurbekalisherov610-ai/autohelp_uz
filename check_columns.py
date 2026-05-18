import asyncio
import sys
sys.path.append('d:/autohelp')

from sqlalchemy.ext.asyncio import create_async_engine
from src.core.config import settings
from sqlalchemy import text

async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name = 'orders' AND is_nullable = 'NO' AND column_default IS NULL;"))
        print("NOT NULL COLUMNS WITHOUT DEFAULT in orders:")
        for row in res.fetchall():
            print(row)
    await engine.dispose()

asyncio.run(main())
