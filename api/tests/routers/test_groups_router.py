from __future__ import annotations

from typing import Any

from api.main import build_app
from api.routers.groups import _groups_service
from fastapi.testclient import TestClient


class _FakeGroupsSvc:
    def __init__(self, result: dict[str, Any] | None) -> None:
        self._result = result

    async def get_members(
        self,
        group_id: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, Any] | None:
        return self._result


def _app_with_groups(result: dict[str, Any] | None) -> TestClient:
    app = build_app()
    app.dependency_overrides[_groups_service] = lambda: _FakeGroupsSvc(result)
    return TestClient(app)


def test_groups_returns_paginated_members() -> None:
    payload = {
        "group_id": "g:sales",
        "group_name": "Sales EMEA",
        "size": 250,
        "members": [f"user{i}@corp" for i in range(100)],
        "next_cursor": "dXNlcjk5QGNvcnA=",
    }
    client = _app_with_groups(payload)
    r = client.get("/api/groups/g:sales", params={"page_size": 100})
    assert r.status_code == 200
    body = r.json()
    assert body["group_id"] == "g:sales"
    assert body["group_name"] == "Sales EMEA"
    assert body["size"] == 250
    assert len(body["members"]) == 100
    assert body["next_cursor"] == "dXNlcjk5QGNvcnA="


def test_groups_returns_404_for_unknown_group() -> None:
    client = _app_with_groups(None)
    r = client.get("/api/groups/g:nope")
    assert r.status_code == 404


def test_groups_rejects_oversize_page() -> None:
    client = _app_with_groups({})
    r = client.get("/api/groups/g:sales", params={"page_size": 500})
    # FastAPI rejects at query validation, returning 422.
    assert r.status_code == 422
