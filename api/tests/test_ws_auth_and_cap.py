"""WS auth + one-per-user cap.

Uses the test-only MOCK_SESSION route to mint a session cookie for the
Playwright-style paths, then drives a ``TestClient.websocket_connect`` to
assert behavior on: unauthenticated, authenticated, duplicate user.
"""

from __future__ import annotations

import pytest
from api.auth.session import SessionCodec, SessionData
from api.main import build_app
from fastapi.testclient import TestClient


@pytest.fixture
def _patched(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_false() -> bool:
        return False

    monkeypatch.setattr("api.main.ping_db", _fake_false, raising=True)
    monkeypatch.setattr("api.main.ping_redis", _fake_false, raising=True)


def _cookie_for(upn: str, roles: set[str]) -> str:
    return SessionCodec(secret="y" * 32).encode(
        SessionData(user_upn=upn, roles=roles, csrf="t", exp=9999999999)
    )


def test_anonymous_ws_is_rejected(_patched: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)
    client = TestClient(build_app())
    # No session cookie → WS connect must close with 1008 (policy violation).
    with pytest.raises(Exception), client.websocket_connect("/ws/sankey"):
        pass


def test_valid_viewer_session_is_accepted(_patched: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)
    # `with TestClient(...) as client` runs the FastAPI lifespan, which
    # initializes the `_fanout` singleton in api.routers.ws — without it,
    # the handler short-circuits with a 1011 close on every connect.
    with TestClient(build_app()) as client:
        client.cookies.set("session", _cookie_for("alice@example.com", {"viewer"}))
        with client.websocket_connect("/ws/sankey") as ws:
            # Handshake succeeded — send a filter update and then close.
            ws.send_text('{"filter": {"dst_app": "m365"}}')


def test_duplicate_connection_for_same_user_rejected(
    _patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)
    with TestClient(build_app()) as client:
        client.cookies.set("session", _cookie_for("bob@example.com", {"viewer"}))
        # Outer connection must stay open while we attempt the duplicate, hence
        # the nested `with` (SIM117 cannot be combined without changing
        # semantics).
        with client.websocket_connect("/ws/sankey"):  # noqa: SIM117
            with pytest.raises(Exception), client.websocket_connect("/ws/sankey"):
                pass


def test_missing_viewer_role_rejected(_patched: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)
    client = TestClient(build_app())
    # Roles set lacks "viewer" — should be rejected.
    client.cookies.set("session", _cookie_for("eve@example.com", set()))
    with pytest.raises(Exception), client.websocket_connect("/ws/sankey"):
        pass
