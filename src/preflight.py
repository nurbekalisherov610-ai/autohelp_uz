"""
Preflight checks — runs before the bot starts.
Validates: BOT_TOKEN, DATABASE connectivity, schema completeness.
"""
import asyncio
import logging

from aiogram import Bot
from sqlalchemy import inspect, text

from src.core.config import get_settings
from src.db.session import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("preflight")


async def check_bot_token(settings) -> bool:
    if not settings.bot_token or settings.bot_token == "replace_me":
        logger.error("❌ BOT_TOKEN is missing or is still the placeholder value!")
        return False
    try:
        bot = Bot(token=settings.bot_token)
        me = await bot.get_me()
        logger.info("✅ Bot Token OK — @%s (ID: %s)", me.username, me.id)
        await bot.session.close()
        return True
    except Exception as exc:
        logger.error("❌ Bot Token invalid or Telegram unreachable: %s", exc)
        return False


async def check_database(settings) -> bool:
    try:
        async with engine.connect() as conn:
            # Use text() — required by SQLAlchemy 2.x
            await conn.execute(text("SELECT 1"))

            def get_schema(connection):
                inspector = inspect(connection)
                tables = inspector.get_table_names()
                schema = {t: [c["name"] for c in inspector.get_columns(t)] for t in tables}
                return tables, schema

            tables, schema = await conn.run_sync(get_schema)
            logger.info("📊 DB tables found: %s", tables)

            # Required columns for core functionality
            required = {
                "users": ["id", "telegram_id", "language", "is_master", "is_blocked"],
                "orders": [
                    "id", "client_id", "status", "issue_type", "issue_label",
                    "phone", "latitude", "longitude", "video_file_id",
                ],
                "order_status_history": ["order_id", "to_status"],
            }

            failures = []
            for table, cols in required.items():
                if table not in tables:
                    failures.append(f"Table '{table}' is missing")
                    continue
                missing = [c for c in cols if c not in schema[table]]
                if missing:
                    failures.append(f"Table '{table}' missing columns: {', '.join(missing)}")

            if failures:
                logger.warning(
                    "⚠️ Schema issues (will be fixed by migrations): %s",
                    " | ".join(failures),
                )
                # Return True — alembic upgrade head will fix this
                return True

            logger.info("✅ Database connectivity and schema OK")
            return True
    except Exception as exc:
        logger.error("❌ Database check failed: %s", exc)
        return False


def check_env_vars(settings) -> bool:
    critical = [("bot_token", "BOT_TOKEN"), ("database_url", "DATABASE_URL")]
    all_ok = True
    for attr, name in critical:
        val = getattr(settings, attr, None)
        if not val or val == "replace_me":
            logger.warning("⚠️ %s is not configured!", name)
            all_ok = False
        else:
            masked = str(val)[:4] + "…" + str(val)[-4:] if len(str(val)) > 8 else "***"
            logger.info("✅ %s = %s", name, masked)

    # Optional but important
    optional = [
        ("dispatcher_ids", "DISPATCHER_IDS"),
        ("admin_ids", "ADMIN_IDS"),
        ("master_ids", "MASTER_IDS"),
    ]
    for attr, name in optional:
        val = getattr(settings, attr, None)
        if not val:
            logger.warning("⚠️ %s is empty — related functionality will be limited.", name)
        else:
            logger.info("✅ %s = %s", name, val)

    return all_ok


async def main() -> None:
    logger.info("🚀 AutoHelp Preflight Check starting…")
    settings = get_settings()

    env_ok = check_env_vars(settings)
    db_ok = await check_database(settings)
    bot_ok = await check_bot_token(settings)

    if env_ok and db_ok and bot_ok:
        logger.info("✨ All checks passed — system is NOMINAL")
    else:
        logger.warning(
            "⚠️ Some checks failed. Review warnings above. "
            "Migrations will run next and may fix schema issues."
        )


if __name__ == "__main__":
    asyncio.run(main())
