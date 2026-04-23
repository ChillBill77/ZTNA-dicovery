"""Verify the test-only routes are 404 when MOCK_SESSION is unset and 200/OK
when set. These routes mint a session cookie + publish to sankey.live for
Playwright E2E; they must never be reachable in production.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import build_app


@pytest.fixture
def _patched(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_false() -> bool:
        return False

    monkeypatch.setattr("api.main.ping_db", _fake_false, raising=True)
    monkeypatch.setattr("api.main.ping_redis", _fake_false, raising=True)


def test_routes_absent_by_default(_patched: None) -> None:
    client = TestClient(build_app())
    r = client.post("/api/test/login-as", json={"upn": "x", "roles": []})
    assert r.status_code == 404


def test_login_as_route_active_when_mock_session_set(
    _patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_SESSION", "1")
    monkeypatch.setenv("SESSION_SECRET", "z" * 32)
    client = TestClient(build_app())
    r = client.post(
        "/api/test/login-as",
        json={"upn": "alice@example.com", "roles": ["viewer"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert "session" in body
    assert "csrf_token" in body
