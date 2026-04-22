from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://ztna:change-me@postgres:5432/ztna"
    redis_url: str = "redis://redis:6379/0"
    log_level: str = "INFO"
