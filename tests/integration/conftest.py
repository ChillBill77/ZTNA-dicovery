from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

COMPOSE_FILES = ["-f", "docker-compose.yml", "-f", "compose.test.yml"]
FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"


def _compose(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *COMPOSE_FILES, *args],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def _wait_for_api_ready(timeout_s: int = 120) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:8000/health/ready", timeout=3) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"api /health/ready did not reach 200 within {timeout_s}s")


@pytest.fixture(scope="session")
def compose_stack() -> Iterator[dict[str, str]]:
    """Bring up docker-compose.yml + compose.test.yml; yield env; tear down."""
    env = os.environ.copy()
    env.setdefault("APP_DOMAIN", "localhost")
    env.setdefault("POSTGRES_USER", "ztna")
    env.setdefault("POSTGRES_PASSWORD", "integration")
    env.setdefault("POSTGRES_DB", "ztna")
    env.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://ztna:integration@postgres:5432/ztna",
    )
    env.setdefault("REDIS_URL", "redis://redis:6379/0")
    env.setdefault("ACME_EMAIL", "")
    # Enable the gated /api/test/login-as route so integration tests can mint
    # session cookies for the (now mandatory) viewer-role gate on data routes.
    env.setdefault("MOCK_SESSION", "1")
    env.setdefault("SESSION_SECRET", "y" * 32)

    _compose(env, "up", "-d", "--build")
    try:
        _wait_for_api_ready()
        yield env
    finally:
        subprocess.run(
            ["docker", "compose", *COMPOSE_FILES, "down", "-v", "--remove-orphans"],
            env=env,
            check=False,
        )


@pytest.fixture
def fixture_path() -> Path:
    return FIXTURE_ROOT


@pytest.fixture
def auth_session(compose_stack: dict[str, str]) -> dict[str, str]:
    """Mint a viewer+editor session via the MOCK_SESSION-only route.

    Returns a dict with two pieces tests need together:

    - ``cookie_header``: ready-to-send ``session=<tok>; csrf_token=<csrf>``
      string for the ``Cookie`` request header. The CsrfMiddleware
      double-submits ``csrf_token`` between the cookie and an
      ``X-CSRF-Token`` header, so both halves must travel.
    - ``csrf_token``: bare value to pass as ``X-CSRF-Token`` on unsafe
      methods (POST/PUT/DELETE).
    """

    import json
    import urllib.request

    req = urllib.request.Request(
        "http://localhost:8000/api/test/login-as",
        method="POST",
        data=json.dumps({"upn": "tester@example.com", "roles": ["viewer", "editor"]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        body = json.loads(r.read())
    return {
        "cookie_header": f"session={body['session']}; csrf_token={body['csrf_token']}",
        "csrf_token": body["csrf_token"],
    }
