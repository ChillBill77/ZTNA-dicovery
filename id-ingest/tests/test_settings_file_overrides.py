"""Verify Docker-secrets-style ``*_FILE`` env vars override Settings fields.

In prod the Compose overlay mounts a Docker secret at
``/run/secrets/<name>`` and exports ``<FIELD>_FILE=/run/secrets/<name>``.
Pydantic Settings normally only reads env vars; this test asserts the
``model_validator(mode="after")`` hook on ``IdIngestSettings`` reads the file
bodies and overwrites the plain-text fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from id_ingest.settings import IdIngestSettings


def test_ad_bind_password_file_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # avoid picking up repo .env
    secret_file = tmp_path / "ad.secret"
    secret_file.write_text("  super-secret-bind-pw  \n")
    monkeypatch.setenv("AD_BIND_PASSWORD", "from-env-ignored")
    monkeypatch.setenv("AD_BIND_PASSWORD_FILE", str(secret_file))

    s = IdIngestSettings()
    assert s.ad_bind_password == "super-secret-bind-pw"


def test_entra_client_secret_file_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    secret_file = tmp_path / "entra.secret"
    secret_file.write_text("entra-client-secret-from-file\n")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "from-env-ignored")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET_FILE", str(secret_file))

    s = IdIngestSettings()
    assert s.entra_client_secret == "entra-client-secret-from-file"


def test_file_override_missing_path_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AD_BIND_PASSWORD", "from-env-used")
    monkeypatch.setenv("AD_BIND_PASSWORD_FILE", str(tmp_path / "nonexistent"))

    s = IdIngestSettings()
    # Path doesn't exist → env var wins, no exception.
    assert s.ad_bind_password == "from-env-used"
