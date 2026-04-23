from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CorrelatorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://ztna:change-me@postgres:5432/ztna"
    flows_stream: str = "flows.raw"
    window_s: int = 5
    queue_max: int = 10_000
    batch_size: int = 10_000
    flush_ms: int = 500
    log_level: str = "INFO"
