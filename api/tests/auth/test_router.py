from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_redirects_to_idp(
    client: TestClient, monkeypatch: __import__("pytest").MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "OIDC_ISSUER", "https://login.microsoftonline.com/tid/v2.0"
    )
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-id")
    monkeypatch.setenv(
        "OIDC_REDIRECT_URI", "https://ztna.example/api/auth/callback"
    )
    r = client.get("/api/auth/login", follow_redirects=False)
    assert r.status_code == 302
    assert "login.microsoftonline.com" in r.headers["location"]
    # State cookie set for CSRF-defense on the callback.
    assert "oidc_state" in r.cookies


def test_callback_sets_session_cookie(
    client_with_mock_idp: TestClient,
    monkeypatch: __import__("pytest").MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)
    monkeypatch.setenv("OIDC_GROUP_IDS_VIEWER", "g-view")
    r = client_with_mock_idp.get(
        "/api/auth/callback?code=abc&state=s1", follow_redirects=False
    )
    assert r.status_code == 302
    assert "session" in r.cookies
    assert "csrf_token" in r.cookies


def test_me_returns_identity_and_roles(authed_client: TestClient) -> None:
    r = authed_client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user_upn"] == "alice@example.com"
    assert body["roles"] == ["viewer"]


def test_logout_clears_session(authed_client: TestClient) -> None:
    r = authed_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": "t123"}
    )
    assert r.status_code == 204
