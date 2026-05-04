from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from api.auth.roles import _current_user_proxy
from api.main import build_app
from api.routers.identity import _identity_service
from fastapi.testclient import TestClient


class _FakeIdSvc:
    def __init__(self, result: dict[str, Any] | None) -> None:
        self._result = result

    async def resolve(self, src_ip: str, at: datetime) -> dict[str, Any] | None:
        return self._result


def _app_with_identity(result: dict[str, Any] | None) -> TestClient:
    app = build_app()
    app.dependency_overrides[_identity_service] = lambda: _FakeIdSvc(result)
    # Bypass auth — these unit tests exercise router logic only.
    app.dependency_overrides[_current_user_proxy] = lambda: {
        "user_upn": "tester@example.com",
        "roles": {"viewer", "editor", "admin"},
    }
    return TestClient(app)


def test_resolve_returns_known_binding() -> None:
    binding = {
        "user_upn": "alice@corp.example",
        "source": "ad_4624",
        "confidence": 90,
        "groups": ["Sales EMEA", "All Staff"],
        "ttl_remaining": 3456,
    }
    client = _app_with_identity(binding)
    r = client.get(
        "/api/identity/resolve",
        params={
            "src_ip": "10.0.12.34",
            "at": datetime(2026, 4, 22, 12, tzinfo=UTC).isoformat(),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_upn"] == "alice@corp.example"
    assert body["source"] == "ad_4624"
    assert body["confidence"] == 90
    assert body["groups"] == ["Sales EMEA", "All Staff"]
    assert body["ttl_remaining"] == 3456


def test_resolve_returns_null_when_no_binding() -> None:
    client = _app_with_identity(None)
    r = client.get(
        "/api/identity/resolve",
        params={
            "src_ip": "192.0.2.1",
            "at": datetime(2026, 4, 22, 12, tzinfo=UTC).isoformat(),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_upn"] is None
    assert body["source"] is None
    assert body["groups"] == []
