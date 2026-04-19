"""Quick test: Neon DB connection + table creation."""
import sys
import asyncio
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

# Import ALL models first so they register with Base.metadata
import models  # noqa: F401

from core.config import settings
from core.database import engine, init_db, close_db


async def test():
    print(f"DB Host: {settings.db_host}")
    print(f"SSL: {settings.db_ssl}")
    print(f"Redis: {settings.use_redis}")
    print()

    # Test basic connection
    from sqlalchemy import text
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        print(f"✅ Database connected! SELECT 1 = {result.scalar()}")

    # Create all tables
    print("\nCreating tables...")
    await init_db()
    print("✅ All tables created!")

    # List tables
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        ))
        tables = [row[0] for row in result.all()]
        print(f"\n📋 Tables in database ({len(tables)}):")
        for t in tables:
            print(f"   • {t}")

    await close_db()
    print("\n🎉 Everything works!")


if __name__ == "__main__":
    asyncio.run(test())
