"""
AutoHelp.uz - Core Configuration Module
Loads all settings from environment variables with validation.
"""
import json
import re
from pathlib import Path
from typing import Annotated, List, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    # ── Telegram Bot ──────────────────────────────────────────────
    bot_token: str
    admin_ids: Annotated[List[int], NoDecode] = []
    admin_staff_ids: Annotated[List[int], NoDecode] = []
    dispatcher_ids: Annotated[List[int], NoDecode] = []
    master_ids: Annotated[List[int], NoDecode] = []
    master_roles: str = ""
    env_bootstrap_enabled: bool = True
    dispatcher_group_id: int = 0
    dispatch_mode: Literal["bot_only", "hybrid", "group_only"] = "bot_only"
    video_channel_id: int = 0
    dispatcher_confirm_video_uz: str = ""
    dispatcher_confirm_video_ru: str = ""
    dispatcher_confirm_video_kind: Literal["video_note", "video"] = "video_note"

    # ── Database ──────────────────────────────────────────────────
    database_url: str = ""  # If provided (e.g. by Railway), overrides individual fields
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "autohelp"
    db_user: str = "autohelp_user"
    db_password: str = ""
    db_ssl: bool = False

    # ── Redis (optional) ──────────────────────────────────────────
    redis_url: str = ""    # If provided (e.g. by Railway), overrides individual fields
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # ── Web Panel ─────────────────────────────────────────────────
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    secret_key: str = "change-me-in-production"

    # ── Backup ────────────────────────────────────────────────────
    backup_path: str = "backups"
    backup_retention_days: int = 30

    # ── SLA Timeouts (minutes) ────────────────────────────────────
    sla_assign_timeout: int = 5
    sla_on_the_way_timeout: int = 60
    sla_confirm_timeout: int = 15
    sla_alert_cooldown_minutes: int = 30
    dispatcher_auto_video_delay_seconds: int = 25
    order_draft_reminder_minutes: int = 10

    # ── Logging ───────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "logs/autohelp.log"

    @staticmethod
    def _parse_id_list(value):
        """
        Accepts ID lists in multiple formats:
        - JSON list: [123, 456]
        - CSV string: 123,456
        - Single int/string: 123
        """
        if value is None:
            return []

        if isinstance(value, list):
            out = []
            for item in value:
                try:
                    out.append(int(item))
                except (TypeError, ValueError):
                    continue
            return out

        if isinstance(value, int):
            return [value]

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []

            # JSON list style
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        out = []
                        for item in parsed:
                            try:
                                out.append(int(item))
                            except (TypeError, ValueError):
                                continue
                        return out
                except json.JSONDecodeError:
                    pass

            # CSV / single value style
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            out = []
            for p in parts:
                try:
                    out.append(int(p))
                except (TypeError, ValueError):
                    pass
            if out:
                return out

            # Last-resort fallback for noisy inputs like "id=123456"
            return [int(x) for x in re.findall(r"-?\d+", raw)]

        return value

    @field_validator("admin_ids", "admin_staff_ids", "dispatcher_ids", "master_ids", mode="before")
    @classmethod
    def parse_id_lists(cls, value):
        return cls._parse_id_list(value)

    @field_validator("dispatch_mode", mode="before")
    @classmethod
    def parse_dispatch_mode(cls, value):
        """Normalize dispatch routing mode from env."""
        if value is None:
            return "bot_only"
        raw = str(value).strip().lower()
        aliases = {
            "bot": "bot_only",
            "direct": "bot_only",
            "private": "bot_only",
            "bot_only": "bot_only",
            "hybrid": "hybrid",
            "mixed": "hybrid",
            "group": "group_only",
            "group_only": "group_only",
        }
        return aliases.get(raw, raw)

    @field_validator("dispatcher_confirm_video_kind", mode="before")
    @classmethod
    def parse_dispatcher_confirm_video_kind(cls, value):
        """Normalize dispatcher auto-confirm media type from env."""
        if value is None:
            return "video_note"
        raw = str(value).strip().lower()
        aliases = {
            "video_note": "video_note",
            "videonote": "video_note",
            "note": "video_note",
            "circle": "video_note",
            "video": "video",
        }
        return aliases.get(raw, raw)

    @property
    def get_database_url(self) -> str:
        """Async PostgreSQL connection URL."""
        import os
        raw_url = os.getenv("DATABASE_URL") or self.database_url
        if raw_url:
            # Railway provides postgres://..., SQLAlchemy needs postgresql+asyncpg://...
            if raw_url.startswith("postgres://"):
                return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
            if raw_url.startswith("postgresql://"):
                return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return raw_url
            
        ssl_param = "?ssl=require" if self.db_ssl else ""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}{ssl_param}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync PostgreSQL connection URL (for Alembic migrations)."""
        ssl_param = "?sslmode=require" if self.db_ssl else ""
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}{ssl_param}"
        )

    @property
    def get_redis_url(self) -> str:
        """Redis connection URL. Empty string if Redis not configured."""
        if self.redis_url:
            return self.redis_url
        if not self.redis_host:
            return ""
        password_part = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{password_part}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def use_redis(self) -> bool:
        """Whether Redis is configured."""
        return bool(self.redis_url) or bool(self.redis_host)


# Singleton settings instance
settings = Settings()

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
LOCALES_DIR = BASE_DIR / "locales"
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"
