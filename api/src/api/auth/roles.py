from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, Request


@dataclass(frozen=True)
class RoleMap:
    """Entra security-group-id sets per role.

    Group-IDs mapped to ``admin`` also imply ``editor`` and ``viewer``; mapping
    to ``editor`` implies ``viewer``. This hierarchy is applied in
    :func:`roles_from_groups`.
    """

    viewer: set[str] = field(default_factory=set)
    editor: set[str] = field(default_factory=set)
    admin: set[str] = field(default_factory=set)


_HIERARCHY: dict[str, set[str]] = {
    "viewer": {"viewer"},
    "editor": {"viewer", "editor"},
    "admin": {"viewer", "editor", "admin"},
}


def roles_from_groups(groups: list[str], mapping: RoleMap) -> set[str]:
    gset = set(groups)
    if gset & mapping.admin:
        return set(_HIERARCHY["admin"])
    if gset & mapping.editor:
        return set(_HIERARCHY["editor"])
    if gset & mapping.viewer:
        return set(_HIERARCHY["viewer"])
    return set()


async def _current_user_proxy(request: Request) -> dict[str, Any]:
    """Late-bound resolver for :func:`require_role`.

    Avoids circular import at module load by resolving the real resolver on
    call. Tests override this via
    ``app.dependency_overrides[_current_user_proxy] = ...``.
    """

    from api.auth.router import current_user

    return await current_user(request)


def require_role(role: str) -> Any:
    """Return a FastAPI dependency that requires ``role`` on the caller."""

    if role not in _HIERARCHY:
        raise ValueError(f"unknown role {role}")

    def _dep(user: dict[str, Any] = Depends(_current_user_proxy)) -> dict[str, Any]:
        if role not in user.get("roles", set()):
            raise HTTPException(status_code=403, detail=f"role '{role}' required")
        return user

    return Depends(_dep)
