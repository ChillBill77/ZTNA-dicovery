from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ResolverSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://ztna:change-me@postgres:5432/ztna"
    rate_per_s: float = 50.0
    ptr_ttl_s: int = 3600
    saas_ttl_s: int = 3600
    log_level: str = "INFO"
