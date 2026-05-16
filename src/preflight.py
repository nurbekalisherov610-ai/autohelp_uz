import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    success: bool
    message: str
    details: Any = None


async def check_bot_token() -> CheckResult:
    if not settings.bot_token:
        return CheckResult("Bot Token", False, "BOT_TOKEN is not set in environment.")
    
    try:
        bot = Bot(token=settings.bot_token)
        me = await bot.get_me()
        await bot.session.close()
        return CheckResult("Bot Token", True, f"Token is valid. Bot: @{me.username}")
    except Exception as exc:
        return CheckResult("Bot Token", False, f"Token validation failed: {exc}")


async def check_database() -> CheckResult:
    url = settings.resolved_database_dsn
    if not url:
        return CheckResult("Database", False, "Database DSN is not resolved.")
    
    try:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            # 1. Check connectivity
            await conn.execute(text("SELECT 1"))
            
            # 2. Check essential tables (User, Order)
            # This helps identify if migrations actually ran
            result = await conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            tables = [row[0] for row in result.fetchall()]
            
            missing = []
            for t in ["users", "orders", "order_status_history"]:
                if t not in tables:
                    missing.append(t)
            
            await engine.dispose()
            
            if missing:
                return CheckResult(
                    "Database", 
                    False, 
                    f"Connected, but tables are missing: {', '.join(missing)}. Did you run migrations?",
                    details={"tables_found": tables}
                )
                
            return CheckResult("Database", True, f"Connected and verified {len(tables)} tables.")
    except Exception as exc:
        return CheckResult("Database", False, f"Connection failed: {exc}")


async def check_redis() -> CheckResult:
    if not settings.use_redis:
        return CheckResult("Redis", True, "Redis is disabled (USE_REDIS=false).")
    
    from redis.asyncio import Redis
    try:
        r = Redis.from_url(settings.redis_dsn)
        await r.ping()
        await r.aclose()
        return CheckResult("Redis", True, "Connected successfully.")
    except Exception as exc:
        return CheckResult("Redis", False, f"Connection failed: {exc}")


async def main():
    logger.info("Starting preflight checks...")
    
    results = [
        await check_bot_token(),
        await check_database(),
        await check_redis(),
    ]
    
    failed = False
    print("\n" + "="*40)
    print(" PREFLIGHT CHECK RESULTS ")
    print("="*40)
    
    for res in results:
        status = "✅ PASS" if res.success else "❌ FAIL"
        print(f"{status} | {res.name}: {res.message}")
        if not res.success:
            failed = True
            if res.details:
                print(f"   Details: {res.details}")
                
    print("="*40)
    
    if failed:
        logger.error("Preflight checks failed! Bot might not function correctly.")
        sys.exit(1)
    else:
        logger.info("All checks passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
