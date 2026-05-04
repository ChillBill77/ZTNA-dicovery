from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Mapping from ``{SECRET}_FILE`` env var → Settings field. In production the
# prod compose overlay mounts Docker secrets at /run/secrets/<name> and sets
# the corresponding ``*_FILE`` env so the pydantic model reads the file body
# and overwrites the plain-text field on the model.
_FILE_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("oidc_client_secret", "OIDC_CLIENT_SECRET_FILE"),
    ("session_secret", "SESSION_SECRET_FILE"),
    ("database_url", "DATABASE_URL_FILE"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = "postgresql+asyncpg://ztna:change-me@postgres:5432/ztna"
    redis_url: str = "redis://redis:6379/0"
    log_level: str = "INFO"

    # --- OIDC / Auth (P4) ---
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_group_ids_viewer: str = ""
    oidc_group_ids_editor: str = ""
    oidc_group_ids_admin: str = ""
    # Session cookie signing key. Must be ≥ 32 bytes in production. Default is
    # long enough to construct SessionCodec in test environments where the env
    # var is not set; production deployments override via SESSION_SECRET or
    # SESSION_SECRET_FILE (Docker secret mount point).
    session_secret: str = "change-me-change-me-change-me-replace"
    access_token_ttl_s: int = 3600

    # Test-only login + seed routes (gated). Set MOCK_SESSION=1 in CI E2E only;
    # never in production.
    mock_session_enabled: bool = Field(
        default=False,
        validation_alias="MOCK_SESSION",
    )

    @model_validator(mode="after")
    def _load_from_files(self) -> Settings:
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
