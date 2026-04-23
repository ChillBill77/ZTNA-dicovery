from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class AdapterConfig:
    enabled: bool = True
    source_ips: frozenset[str] = field(default_factory=frozenset)


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://redis:6379/0"
    syslog_host: str = "0.0.0.0"
    syslog_port: int = 5514
    config_dir: str = "/etc/flowvis/adapters"
    log_level: str = "INFO"
    queue_max: int = 10_000


def load_adapter_configs(path: Path) -> dict[str, AdapterConfig]:
    out: dict[str, AdapterConfig] = {}
    for yml in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(yml.read_text()) or {}
        out[yml.stem] = AdapterConfig(
            enabled=bool(data.get("enabled", True)),
            source_ips=frozenset(data.get("source_ips", []) or []),
        )
    return out
