from pathlib import Path

from api.settings import Settings


def test_settings_loads_from_env(monkeypatch, tmp_path: Path) -> None:
    # Isolate from any repo-root .env that may exist locally.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv("REDIS_URL", "redis://r:6379/0")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    s = Settings()

    assert s.database_url == "postgresql+asyncpg://x/y"
    assert s.redis_url == "redis://r:6379/0"
    assert s.log_level == "DEBUG"


def test_settings_defaults_when_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)        # no .env in cwd
    for var in ("DATABASE_URL", "REDIS_URL", "LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)

    s = Settings()

    assert s.database_url == "postgresql+asyncpg://ztna:change-me@postgres:5432/ztna"
    assert s.redis_url == "redis://redis:6379/0"
    assert s.log_level == "INFO"
