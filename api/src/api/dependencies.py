from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session as _get_session
from api.redis import get_redis as _get_redis


async def db_session() -> AsyncIterator[AsyncSession]:
    async for s in _get_session():
        yield s


def redis_client() -> Redis:
    return _get_redis()


async def current_user(request: Request) -> dict[str, Any]:
    """Backwards-compatible alias for :func:`api.auth.router.current_user`.

    Retained so older imports continue to resolve; new code should depend on
    ``api.auth.roles._current_user_proxy`` (used by ``require_role``).
    """

    from api.auth.router import current_user as real_current_user

    return await real_current_user(request)


async def require_editor(request: Request) -> dict[str, Any]:
    """Dependency requiring the caller hold the ``editor`` role.

    Kept under this name so P2/P3 CRUD routers using ``Depends(require_editor)``
    get real RBAC enforcement without per-route edits.
    """

    from api.auth.roles import _current_user_proxy

    user = await _current_user_proxy(request)
    if "editor" not in user.get("roles", set()):
        raise HTTPException(status_code=403, detail="role 'editor' required")
    return user
