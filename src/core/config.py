from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_CHAT_IDS = {-1000000000000}


def _parse_int_list(value: str | None) -> list[int]:
    if not value:
        return []

    ids: list[int] = []
    for raw in value.split(","):
        item = raw.strip()
        if item.lstrip("-").isdigit():
            ids.append(int(item))
    return ids


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AutoHelp"
    app_env: str = "dev"
    log_level: str = "INFO"

    bot_token: str | None = None
    dispatcher_chat_id: int | None = None
    dispatcher_ids: str | None = None        # comma-separated list e.g. "123456789,987654321"
    dispatcher_group_id: int | None = None
    admin_chat_id: int | None = None
    admin_ids: str | None = None             # comma-separated admin telegram IDs
    master_ids: str | None = None            # comma-separated list of master telegram IDs
    master_labels: str | None = None         # comma-separated labels for masters
    master_secret: str = "master123"         # secret code to self-register as master
    dispatcher_confirm_video_kind: str | None = None
    dispatcher_confirm_video_uz: str | None = None
    dispatcher_confirm_video_ru: str | None = None
    dispatcher_confirm_video_en: str | None = None

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "autohelp"
    postgres_user: str = "autohelp"
    postgres_password: str = "autohelp"
    database_url: str | None = None

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_url: str | None = None
    use_redis: bool = True

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    timezone: str = "Asia/Tashkent"
    auto_create_schema: bool = False
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
    def parsed_master_labels(self) -> list[str]:
        if not self.master_labels:
            return []
        return [label.strip() for label in self.master_labels.split(",")]

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def resolved_dispatcher_chat_id(self) -> int | None:
        """Return the best chat destination for dispatcher alerts.

        Railway often has both DISPATCHER_IDS (allowed people) and
        DISPATCHER_GROUP_ID (operations room). Prefer the group for alerts,
        ignore template placeholders, then fall back to a direct dispatcher id.
        """
        candidates = [
            self.dispatcher_group_id,
            self.dispatcher_chat_id,
            self.parsed_dispatcher_ids[0] if self.parsed_dispatcher_ids else None,
        ]
        for candidate in candidates:
            if candidate is not None and candidate not in PLACEHOLDER_CHAT_IDS:
                return candidate
        return None

    def confirmation_video_file_id(self, language: str | None) -> str | None:
        lang = (language or "uz").lower()
        if lang.startswith("ru"):
            return self.dispatcher_confirm_video_ru or self.dispatcher_confirm_video_uz
        if lang.startswith("en"):
            return self.dispatcher_confirm_video_en or self.dispatcher_confirm_video_uz
        return self.dispatcher_confirm_video_uz or self.dispatcher_confirm_video_ru

    @property
    def resolved_database_dsn(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return self.postgres_dsn

    @property
    def redis_dsn(self) -> str:
        if self.redis_url:
            return self.redis_url
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
