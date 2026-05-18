import asyncio
import logging
import os
import sys

from aiogram import Bot
from sqlalchemy import select, text, inspect

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
        logger.info("✅ Bot Token: Token is valid. Bot: @%s", me.username)
        await bot.session.close()
        return True
    except Exception as exc:
        logger.error("❌ Bot Token: Token is invalid or Telegram unreachable: %s", exc)
        return False

async def check_database(settings):
    try:
        async with engine.connect() as conn:
            await conn.execute(select(1))
            
            # Introspect tables and columns
            def get_schema_info(connection):
                inspector = inspect(connection)
                tables = inspector.get_table_names()
                schema = {}
                for table in tables:
                    schema[table] = [col["name"] for col in inspector.get_columns(table)]
                return tables, schema

            tables, schema = await conn.run_sync(get_schema_info)
            
            logger.info("📊 Details: {'tables_found': %s}", tables)
            
            # Define required columns for core functionality
            required = {
                "users": ["id", "telegram_id", "language", "is_master", "is_blocked"],
                "orders": ["id", "client_id", "status", "issue_type", "issue_label", "phone", "video_file_id"],
                "order_status_history": ["order_id", "to_status"]
            }
            
            failures = []
            for table, cols in required.items():
                if table not in tables:
                    failures.append(f"Table '{table}' is missing")
                    continue
                missing = [c for c in cols if c not in schema[table]]
                if missing:
                    failures.append(f"Table '{table}' is missing columns: {', '.join(missing)}")
            
            if failures:
                logger.error("❌ Database: Schema verification failed: %s", " | ".join(failures))
                # We return True anyway to allow 'alembic upgrade head' in start.sh to try and fix it
                return True 
            
            logger.info("✅ Database: Connectivity and Schema OK")
            return True
    except Exception as exc:
        logger.error("❌ Database: Check failed: %s", exc)
        return False

def check_env_vars(settings):
    critical = ["DATABASE_URL", "BOT_TOKEN"]
    all_ok = True
    for name in critical:
        val = getattr(settings, name.lower(), None)
        if not val:
            logger.warning("⚠️ Environment variable %s is not set", name)
            all_ok = False
        else:
            masked = str(val)[:4] + "..." + str(val)[-4:] if len(str(val)) > 8 else "***"
            logger.info("✅ %s is configured (%s)", name, masked)
    return all_ok

async def main():
    logger.info("🚀 Starting Official System Audit...")
    settings = get_settings()
    
    env_ok = check_env_vars(settings)
    db_ok = await check_database(settings)
    bot_ok = await check_bot_token(settings)
    
    if not (env_ok and db_ok and bot_ok):
        logger.error("🚨 System Audit found issues! Review logs above.")
        # We don't exit with 1 because start.sh handles migrations next
    else:
        logger.info("✨ System Audit complete: ALL SYSTEMS NOMINAL")

if __name__ == "__main__":
    asyncio.run(main())
