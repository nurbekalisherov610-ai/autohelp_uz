"""
AutoHelp.uz - Backup Task
Daily PostgreSQL backup at 03:00 with retention management.
"""
import asyncio
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from core.config import settings


async def run_daily_backup(bot):
    """
    Create a PostgreSQL dump and manage retention.
    Runs daily at 03:00 via APScheduler.
    """
    backup_dir = Path(settings.backup_path)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"autohelp_backup_{timestamp}.backup"
    filepath = backup_dir / filename

    # Build pg_dump command
    db_host = settings.db_host
    db_port = settings.db_port
    db_user = settings.db_user
    db_name = settings.db_name
    db_password = settings.db_password

    # If DATABASE_URL is present (Railway-style), prefer parsed values.
    if os.getenv("DATABASE_URL") or settings.database_url:
        parsed = urlparse(
            settings.get_database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        )
        db_host = parsed.hostname or db_host
        db_port = parsed.port or db_port
        db_user = parsed.username or db_user
        db_name = (parsed.path or "").lstrip("/") or db_name
        db_password = parsed.password or db_password

    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    if settings.db_ssl or "sslmode=require" in settings.database_url_sync:
        env["PGSSLMODE"] = "require"
    cmd = (
        f"pg_dump -h {db_host} -p {db_port} "
        f"-U {db_user} -d {db_name} "
        f"--format=custom --compress=9 -f {filepath}"
    )

    logger.info(f"Starting database backup: {filename}")

    try:
        # Run pg_dump in a subprocess
        process = await asyncio.create_subprocess_shell(
            cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"Backup failed: {error_msg}")

            # Notify admin
            for admin_id in settings.admin_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        f"❌ <b>Backup xatolik!</b>\n\n"
                        f"<code>{error_msg[:500]}</code>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            return

        # Check file size
        file_size = filepath.stat().st_size if filepath.exists() else 0
        size_mb = file_size / (1024 * 1024)

        logger.info(f"Backup completed: {filename} ({size_mb:.1f} MB)")

        # Clean old backups (retention)
        await _cleanup_old_backups(backup_dir)

        # Notify admin
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    f"✅ <b>Kunlik backup tayyor!</b>\n\n"
                    f"📁 Fayl: <code>{filename}</code>\n"
                    f"📊 Hajmi: {size_mb:.1f} MB\n"
                    f"🕐 Vaqt: {datetime.utcnow().strftime('%H:%M %d.%m.%Y')}",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    except Exception as e:
        logger.exception(f"Backup process error: {e}")


async def _cleanup_old_backups(backup_dir: Path):
    """Remove backups older than retention period."""
    retention_days = settings.backup_retention_days
    cutoff = datetime.utcnow().timestamp() - (retention_days * 86400)

    removed = 0
    for f in backup_dir.glob("autohelp_backup_*"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1

    if removed:
        logger.info(f"Cleaned up {removed} old backup(s)")
