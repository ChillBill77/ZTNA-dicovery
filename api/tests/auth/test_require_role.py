from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/applications"),
        ("POST", "/api/applications"),
        ("PUT", "/api/applications/1"),
        ("DELETE", "/api/applications/1"),
        ("GET", "/api/applications/1/audit"),
        ("GET", "/api/saas"),
        ("POST", "/api/saas"),
        ("PUT", "/api/saas/1"),
        ("DELETE", "/api/saas/1"),
        ("GET", "/api/adapters"),
        ("GET", "/api/stats"),
        ("GET", "/api/flows/sankey"),
        ("GET", "/api/flows/raw"),
        ("GET", "/api/identity/resolve?src_ip=1.1.1.1&at=2026-04-22T12:00:00Z"),
        ("GET", "/api/groups/g:sales"),
    ],
)
def test_every_crud_route_is_role_guarded(
    anon_client: TestClient, method: str, path: str
) -> None:
    r = anon_client.request(method, path)
    assert r.status_code in (401, 403, 422), (
        f"{method} {path} returned {r.status_code}; expected auth-gate"
    )
