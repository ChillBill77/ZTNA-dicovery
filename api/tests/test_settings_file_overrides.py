"""Verify Docker-secrets-style ``*_FILE`` env vars override Settings fields.

In prod the Compose overlay mounts a Docker secret at
``/run/secrets/<name>`` and exports ``<FIELD>_FILE=/run/secrets/<name>``.
Pydantic Settings normally only reads env vars; this test asserts the
``model_validator(mode="after")`` hook on the Settings class reads the file
bodies and overwrites the plain-text fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.settings import Settings


def test_session_secret_file_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # avoid picking up repo .env
    secret_file = tmp_path / "session.secret"
    secret_file.write_text("f" * 32 + "\n")
    monkeypatch.setenv("SESSION_SECRET", "from-env-ignored")
    monkeypatch.setenv("SESSION_SECRET_FILE", str(secret_file))

    s = Settings()
    assert s.session_secret == "f" * 32


def test_oidc_client_secret_file_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    secret_file = tmp_path / "oidc.secret"
    secret_file.write_text("  super-secret-from-file  \n")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "from-env-ignored")
    monkeypatch.setenv("OIDC_CLIENT_SECRET_FILE", str(secret_file))

    s = Settings()
    assert s.oidc_client_secret == "super-secret-from-file"


def test_file_override_missing_path_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SESSION_SECRET", "from-env-used")
    monkeypatch.setenv(
        "SESSION_SECRET_FILE", str(tmp_path / "nonexistent")
    )

    s = Settings()
    # Path doesn't exist → env var wins, no exception.
    assert s.session_secret == "from-env-used"


def test_no_env_no_file_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "SESSION_SECRET",
        "SESSION_SECRET_FILE",
        "OIDC_CLIENT_SECRET",
        "OIDC_CLIENT_SECRET_FILE",
    ):
        monkeypatch.delenv(name, raising=False)

    s = Settings()
    assert s.session_secret == "change-me-change-me-change-me-replace"
