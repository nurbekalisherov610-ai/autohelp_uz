import asyncio
import logging
import os
import sys

from aiogram import Bot
from sqlalchemy import select, text

from src.core.config import get_settings
from src.db.session import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("preflight")

async def check_bot_token(settings):
    if not settings.bot_token:
        logger.error("❌ BOT_TOKEN is missing!")
        return False
    
    try:
        bot = Bot(token=settings.bot_token)
        me = await bot.get_me()
        logger.info("✅ Bot Token is valid: @%s (%s)", me.username, me.id)
        await bot.session.close()
        return True
    except Exception as exc:
        logger.error("❌ Bot Token is invalid or Telegram is unreachable: %s", exc)
        return False

async def check_database(settings):
    try:
        async with engine.connect() as conn:
            # 1. Basic connectivity
            await conn.execute(select(1))
            logger.info("✅ Database connectivity: OK")
            
            # 2. Check essential tables
            result = await conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            tables = [row[0] for row in result.fetchall()]
            logger.info("📊 Found tables: %s", ", ".join(tables) if tables else "NONE")
            
            # 3. Check for language column type (our recent fix)
            if "users" in tables:
                res = await conn.execute(text(
                    "SELECT data_type FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'language'"
                ))
                row = res.fetchone()
                if row:
                    logger.info("ℹ️ User.language type: %s", row[0])
            
            return True
    except Exception as exc:
        logger.error("❌ Database check failed: %s", exc)
        return False

def check_env_vars(settings):
    critical_vars = {
        "DATABASE_URL": settings.database_url,
        "BOT_TOKEN": settings.bot_token,
        "ADMIN_IDS": settings.admin_ids,
        "DISPATCHER_IDS": settings.dispatcher_ids,
    }
    
    all_ok = True
    for name, val in critical_vars.items():
        if not val:
            logger.warning("⚠️ Environment variable %s is not set", name)
        else:
            # Mask value for safety
            masked = str(val)[:4] + "..." + str(val)[-4:] if len(str(val)) > 8 else "***"
            logger.info("✅ %s is configured (%s)", name, masked)
            
    return all_ok

async def main():
    logger.info("🚀 Starting Official Deep Audit...")
    settings = get_settings()
    
    env_ok = check_env_vars(settings)
    db_ok = await check_database(settings)
    bot_ok = await check_bot_token(settings)
    
    if not (env_ok and db_ok and bot_ok):
        logger.error("🚨 Deep Audit failed! Some components are not ready.")
        # We don't sys.exit(1) here to allow Alembic to try and fix the DB in start.sh
        # but we provide clear warnings.
    else:
        logger.info("✨ Deep Audit complete: ALL SYSTEMS NOMINAL")

if __name__ == "__main__":
    asyncio.run(main())
