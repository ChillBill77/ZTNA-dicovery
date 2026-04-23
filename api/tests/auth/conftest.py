from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.auth.session import SessionCodec, SessionData


@pytest.fixture
def _app_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build an app with DB/Redis probes stubbed out.

    Tests that want a real identity dependency chain compose this with
    additional ``monkeypatch`` calls.
    """

    async def _fake_false() -> bool:
        return False

    monkeypatch.setattr("api.main.ping_db", _fake_false, raising=True)
    monkeypatch.setattr("api.main.ping_redis", _fake_false, raising=True)
    from api.main import build_app

    return build_app


@pytest.fixture
def client(_app_factory: Any) -> TestClient:
    return TestClient(_app_factory())


@pytest.fixture
def anon_client(_app_factory: Any) -> TestClient:
    return TestClient(_app_factory())


@pytest.fixture
def client_with_mock_idp(
    _app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    async def _fake_exchange(code: str) -> dict[str, Any]:
        return {"upn": "alice@example.com", "groups": ["g-view"]}

    # Patch the oidc module so the router's in-function import finds the fake.
    import api.auth.oidc as oidc_mod

    monkeypatch.setattr(oidc_mod, "exchange_code", AsyncMock(side_effect=_fake_exchange))

    c = TestClient(_app_factory())
    # Seed the oidc_state cookie so the callback's state check passes.
    c.cookies.set("oidc_state", "s1")
    return c


def _authed_client_with(
    _app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    roles: set[str],
    upn: str = "alice@example.com",
) -> TestClient:
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    c = TestClient(_app_factory())
    codec = SessionCodec(secret="x" * 32)
    token = codec.encode(
        SessionData(user_upn=upn, roles=roles, csrf="t123", exp=9999999999)
    )
    c.cookies.set("session", token)
    c.cookies.set("csrf_token", "t123")
    return c


@pytest.fixture
def authed_client(
    _app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    return _authed_client_with(_app_factory, monkeypatch, roles={"viewer"})


@pytest.fixture
def authed_viewer_client(
    _app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    return _authed_client_with(_app_factory, monkeypatch, roles={"viewer"})


@pytest.fixture
def authed_editor_client(
    _app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    return _authed_client_with(
        _app_factory, monkeypatch, roles={"viewer", "editor"}
    )


@pytest.fixture
def authed_admin_client(
    _app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    return _authed_client_with(
        _app_factory,
        monkeypatch,
        roles={"viewer", "editor", "admin"},
    )
