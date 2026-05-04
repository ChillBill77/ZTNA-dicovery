from __future__ import annotations

from typing import Any

import pytest
from api.auth.roles import RoleMap, require_role, roles_from_groups
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROLE_MAP = RoleMap(viewer={"g-view"}, editor={"g-edit"}, admin={"g-admin"})


def test_roles_from_groups_maps_admin_editor_viewer() -> None:
    assert roles_from_groups(["g-admin"], ROLE_MAP) == {"admin", "editor", "viewer"}
    assert roles_from_groups(["g-edit"], ROLE_MAP) == {"editor", "viewer"}
    assert roles_from_groups(["g-view"], ROLE_MAP) == {"viewer"}
    assert roles_from_groups(["g-unknown"], ROLE_MAP) == set()


def test_empty_groups_no_roles() -> None:
    assert roles_from_groups([], ROLE_MAP) == set()


def test_admin_group_in_mixed_list_still_resolves_admin() -> None:
    # Admin takes precedence over editor/viewer when a user belongs to more
    # than one mapped group.
    assert roles_from_groups(["g-view", "g-admin"], ROLE_MAP) == {
        "viewer",
        "editor",
        "admin",
    }


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()

    @a.get("/viewer", dependencies=[require_role("viewer")])
    async def v() -> dict[str, Any]:
        return {"ok": True}

    @a.get("/editor", dependencies=[require_role("editor")])
    async def e() -> dict[str, Any]:
        return {"ok": True}

    @a.get("/admin", dependencies=[require_role("admin")])
    async def ad() -> dict[str, Any]:
        return {"ok": True}

    return a


def _with_roles(roles: set[str]) -> Any:
    async def _dep() -> dict[str, Any]:
        return {"roles": roles}

    return _dep


def test_require_role_allows_same_role(app: FastAPI) -> None:
    from api.auth.roles import _current_user_proxy

    app.dependency_overrides[_current_user_proxy] = _with_roles({"viewer"})
    client = TestClient(app)
    assert client.get("/viewer").status_code == 200


def test_require_role_promotes_higher(app: FastAPI) -> None:
    from api.auth.roles import _current_user_proxy

    app.dependency_overrides[_current_user_proxy] = _with_roles({"admin", "editor", "viewer"})
    client = TestClient(app)
    assert client.get("/viewer").status_code == 200
    assert client.get("/editor").status_code == 200
    assert client.get("/admin").status_code == 200


def test_require_role_denies_lower(app: FastAPI) -> None:
    from api.auth.roles import _current_user_proxy

    app.dependency_overrides[_current_user_proxy] = _with_roles({"viewer"})
    client = TestClient(app)
    assert client.get("/editor").status_code == 403
    assert client.get("/admin").status_code == 403


def test_unauthenticated_denied(app: FastAPI) -> None:
    from api.auth.roles import _current_user_proxy

    async def _anon() -> dict[str, Any]:
        raise HTTPException(status_code=401, detail="unauthenticated")

    app.dependency_overrides[_current_user_proxy] = _anon
    client = TestClient(app)
    assert client.get("/viewer").status_code == 401
