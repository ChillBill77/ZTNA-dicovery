from __future__ import annotations

import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Mapping from ``{SECRET}_FILE`` env var → Settings field. In production the
# prod compose overlay mounts Docker secrets at /run/secrets/<name> and sets
# the corresponding ``*_FILE`` env so the pydantic model reads the file body
# and overwrites the plain-text field on the model.
_FILE_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("ad_bind_password", "AD_BIND_PASSWORD_FILE"),
    ("entra_client_secret", "ENTRA_CLIENT_SECRET_FILE"),
)


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
    # Internal listener port. Traefik forwards external :516 → this port so the
    # container can run as non-root (uid 1001) without CAP_NET_BIND_SERVICE.
    ad_syslog_port: int = 5516

    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_corp_cidrs: str = "10.0.0.0/8,192.168.0.0/16"
    entra_poll_interval_s: int = 60

    # Internal listener ports — see ad_syslog_port note above.
    ise_syslog_port: int = 5517
    clearpass_syslog_port: int = 5518

    group_sync_full_cron: str = "0 2 * * *"
    metrics_port: int = 9100

    @model_validator(mode="after")
    def _load_from_files(self) -> "IdIngestSettings":
        """Resolve ``{FIELD}_FILE`` env vars after normal env parsing.

        For each entry in ``_FILE_OVERRIDES``: if the env var names an existing
        file, read its stripped contents and overwrite the corresponding
        field. Non-existent paths and unset env vars are silently ignored so
        dev/test flows that don't use Docker secrets keep working.
        """

        for attr, env_name in _FILE_OVERRIDES:
            path = os.environ.get(env_name)
            if not path:
                continue
            p = Path(path)
            if p.is_file():
                setattr(self, attr, p.read_text().strip())
        return self
