from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
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
    # var is not set; production deployments override via SESSION_SECRET.
    session_secret: str = "change-me-change-me-change-me-replace"
    access_token_ttl_s: int = 3600
