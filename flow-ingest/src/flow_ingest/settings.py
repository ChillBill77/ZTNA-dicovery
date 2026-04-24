from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# Backwards-compatible re-export: the YAML loader and AdapterConfig dataclass
# now live in ztna_common so both flow-ingest and id-ingest share the shape.
from ztna_common.config import AdapterConfig, load_adapter_configs

__all__ = ["AdapterConfig", "IngestSettings", "load_adapter_configs"]


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://redis:6379/0"
    syslog_host: str = "0.0.0.0"
    syslog_port: int = 5514
    config_dir: str = "/etc/flowvis/adapters"
    log_level: str = "INFO"
    queue_max: int = 10_000
    metrics_port: int = 9100
