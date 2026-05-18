import logging
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PLACEHOLDER_CHAT_IDS = {-1000000000000}

def _parse_int_list(value: str | None) -> list[int]:
    if not value: return []
    ids: list[int] = []
    for raw in value.split(","):
        item = raw.strip()
        if item.lstrip("-").isdigit():
            ids.append(int(item))
    return ids

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("dispatcher_chat_id", "dispatcher_group_id", "admin_chat_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: Any) -> Any:
        if v == "":
            return None
        return v

    app_name: str = "AutoHelp"
    app_env: str = "dev"
    log_level: str = "INFO"
    log_file: str | None = None
    secret_key: str = "super-secret"

    bot_token: str | None = None
    
    # API Settings
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    
    # Dispatcher Settings
    dispatcher_ids: str | None = None
    dispatcher_chat_id: int | None = None
    dispatcher_group_id: int | None = None
    
    # Admin Settings
    admin_ids: str | None = None
    admin_chat_id: int | None = None
    
    # Master Settings
    master_ids: str | None = None
    master_labels: str | None = None
    master_secret: str = "master123"
    
    # Video IDs
    dispatcher_confirm_video_kind: str | None = None
    dispatcher_confirm_video_uz: str | None = None
    dispatcher_confirm_video_ru: str | None = None
    dispatcher_confirm_video_en: str | None = None
    
    # Database
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "autohelp"
    postgres_user: str = "autohelp"
    postgres_password: str = "autohelp"
    
    # Redis
    redis_url: str | None = None
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    use_redis: bool = True
    
    # SLA & Timeouts
    sla_assign_timeout: int = 300   # Default 5 min
    sla_confirm_timeout: int = 600  # Default 10 min
    timezone: str = "Asia/Tashkent"
    
    # Backups
    backup_path: str = "/var/backups/autohelp"
    backup_retention_days: int = 30
    
    # Internal
    auto_create_schema: bool = True
    dependency_wait_attempts: int = 30
    dependency_wait_delay_seconds: float = 2.0

    @property
    def parsed_dispatcher_ids(self) -> list[int]:
        return _parse_int_list(self.dispatcher_ids)

    @property
    def parsed_admin_ids(self) -> list[int]:
        return _parse_int_list(self.admin_ids)

    @property
    def parsed_master_ids(self) -> list[int]:
        return _parse_int_list(self.master_ids)

    @property
    def parsed_master_labels_map(self) -> dict[int, str]:
        """Parse 'ID=Name,ID=Name' or 'Name,Name' formats."""
        if not self.master_labels:
            return {}
        
        result = {}
        parts = [p.strip() for p in self.master_labels.split(",")]
        
        for i, part in enumerate(parts):
            if "=" in part:
                try:
                    k, v = part.split("=", 1)
                    result[int(k.strip())] = v.strip()
                except ValueError:
                    pass
            else:
                # Fallback to index-based mapping if simple list provided
                ids = self.parsed_master_ids
                if i < len(ids):
                    result[ids[i]] = part
        return result

    @property
    def parsed_master_labels(self) -> list[str]:
        """Maintains backward compatibility with list-based access."""
        m_map = self.parsed_master_labels_map
        return [m_map.get(m_id, str(m_id)) for m_id in self.parsed_master_ids]

    @property
    def resolved_dispatcher_chat_id(self) -> int | None:
        candidates = [
            self.dispatcher_group_id,
            self.dispatcher_chat_id,
            self.parsed_dispatcher_ids[0] if self.parsed_dispatcher_ids else None,
        ]
        for c in candidates:
            if c is not None and c not in PLACEHOLDER_CHAT_IDS:
                return c
        return None

    @property
    def resolved_database_dsn(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def redis_dsn(self) -> str:
        if self.redis_url: return self.redis_url
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def confirmation_video_file_id(self, language: str | None) -> str | None:
        lang = (language or "uz").lower()
        if lang.startswith("ru"): return self.dispatcher_confirm_video_ru or self.dispatcher_confirm_video_uz
        if lang.startswith("en"): return self.dispatcher_confirm_video_en or self.dispatcher_confirm_video_uz
        return self.dispatcher_confirm_video_uz or self.dispatcher_confirm_video_ru

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
