"""Smoke test: `docker compose up` → migrate runs → api /health/ready returns 200.

Skipped when DOCKER_SMOKE is not set (so unit CI is fast). Runs in a dedicated
compose-smoke CI job that sets DOCKER_SMOKE=1.

A passing smoke test requires:
  - migrate container ran to completion with exit code 0
  - api's /health/ready returns 200 with both components healthy
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

DOCKER_SMOKE = os.environ.get("DOCKER_SMOKE") == "1"
pytestmark = pytest.mark.skipif(not DOCKER_SMOKE, reason="DOCKER_SMOKE not set")

COMPOSE_FILES = ["-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]


def _compose(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *COMPOSE_FILES, *args],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def _probe_ready(env: dict[str, str], timeout_s: int = 120) -> dict[str, object]:
    """Call /health/ready from inside the api container until it returns 200.

    Returns the parsed JSON body. Raises on timeout or non-200 status.
    """
    deadline = time.monotonic() + timeout_s
    last_err: str = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "compose",
                *COMPOSE_FILES,
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import json,sys,urllib.request;"
                "r=urllib.request.urlopen('http://localhost:8000/health/ready');"
                "sys.stdout.write(str(r.status)+'\\n'+r.read().decode())",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            status_line, _, body = result.stdout.partition("\n")
            if status_line.strip() == "200":
                return json.loads(body)
            last_err = f"HTTP {status_line.strip()}: {body.strip()}"
        else:
            last_err = result.stderr.strip() or result.stdout.strip()
        time.sleep(2)
    raise TimeoutError(f"/health/ready not 200 within {timeout_s}s: {last_err}")


@pytest.fixture
def smoke_env() -> dict[str, str]:
    env = os.environ.copy()
    env["APP_DOMAIN"] = "localhost"
    env["POSTGRES_USER"] = "ztna"
    env["POSTGRES_PASSWORD"] = "smoke"
    env["POSTGRES_DB"] = "ztna"
    env["DATABASE_URL"] = "postgresql+asyncpg://ztna:smoke@postgres:5432/ztna"
    env["REDIS_URL"] = "redis://redis:6379/0"
    env["ACME_EMAIL"] = ""
    return env


def test_stack_comes_up_and_migrate_applies(smoke_env: dict[str, str]) -> None:
    _compose(smoke_env, "up", "-d", "--build")
    try:
        # migrate must have exited successfully (it runs once and exits).
        ps = subprocess.run(
            ["docker", "compose", *COMPOSE_FILES, "ps", "-a", "--format", "json", "migrate"],
            env=smoke_env,
            text=True,
            capture_output=True,
            check=True,
        )
        # `ps --format json` emits one JSON object per line; parse whichever form.
        raw = ps.stdout.strip()
        rows = (
            [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
            if raw.startswith("{")
            else json.loads(raw)
            if raw
            else []
        )
        assert rows, "migrate container not found in docker compose ps"
        migrate_state = rows[0]
        assert migrate_state.get("ExitCode", 1) == 0, (
            f"migrate did not exit cleanly: {migrate_state}"
        )

        body = _probe_ready(smoke_env)
        assert body == {"status": "ok", "components": {"db": True, "redis": True}}, body
    finally:
        subprocess.run(
            ["docker", "compose", *COMPOSE_FILES, "down", "-v", "--remove-orphans"],
            env=smoke_env,
            check=False,
        )
