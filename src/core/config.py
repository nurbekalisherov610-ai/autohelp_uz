from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def resolved_dispatcher_chat_id(self) -> int | None:
        """Return dispatcher_chat_id, falling back to the first value in
        dispatcher_ids, then to dispatcher_group_id."""
        if self.dispatcher_chat_id is not None:
            return self.dispatcher_chat_id
        if self.dispatcher_ids:
            first = self.dispatcher_ids.split(",")[0].strip()
            if first:
                try:
                    return int(first)
                except ValueError:
                    pass
        return self.dispatcher_group_id

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
