"""
AutoHelp.uz - Logger Configuration
Structured logging with Loguru for production reliability.
"""
import sys
from pathlib import Path
from loguru import logger

from core.config import settings


def setup_logger():
    """Configure Loguru for production use."""
    # Remove default handler
    logger.remove()

    # Force UTF-8 on Windows console
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Console output (colorized)
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File output (rotated daily, kept for 30 days)
    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_path),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="00:00",      # Rotate at midnight
        retention="30 days",   # Keep logs for 30 days
        compression="zip",     # Compress old logs
        encoding="utf-8",
        serialize=False,
    )

    # Error-specific log file
    error_path = log_path.parent / "errors.log"
    logger.add(
        str(error_path),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}\n{exception}",
        rotation="1 week",
        retention="90 days",
        compression="zip",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )

    logger.info("Logger initialized successfully")
    return logger
