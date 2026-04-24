from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class IdIngestSettings(BaseSettings):
    """Settings for id-ingest service.

    Env vars without a prefix match docker-compose/.env layout shared across the
    stack (REDIS_URL, DATABASE_URL, LOG_LEVEL, etc.). Adapter-specific knobs live
    under AD_*/ENTRA_* namespaces.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://ztna:change-me@postgres:5432/ztna"
    adapter_config_dir: str = "/etc/flowvis/adapters"
    health_port: int = 8081
    log_level: str = "INFO"

    ad_ldap_url: str = ""
    ad_bind_dn: str = ""
    ad_bind_password: str = ""
    ad_base_dn: str = ""
    ad_syslog_port: int = 516

    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_corp_cidrs: str = "10.0.0.0/8,192.168.0.0/16"
    entra_poll_interval_s: int = 60

    ise_syslog_port: int = 517
    clearpass_syslog_port: int = 518

    group_sync_full_cron: str = "0 2 * * *"
    metrics_port: int = 9100
