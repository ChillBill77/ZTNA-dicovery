from __future__ import annotations

from fastapi.testclient import TestClient


def test_verify_200_for_valid_session(authed_client: TestClient) -> None:
    r = authed_client.get("/auth/verify")
    assert r.status_code == 200
    assert r.headers.get("X-User") == "alice@example.com"
    assert "viewer" in r.headers.get("X-Roles", "")


def test_verify_401_for_anon(client: TestClient) -> None:
    r = client.get("/auth/verify")
    assert r.status_code == 401
