from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session as _get_session
from api.redis import get_redis as _get_redis


async def db_session() -> AsyncIterator[AsyncSession]:
    async for s in _get_session():
        yield s


def redis_client() -> Redis:
    return _get_redis()


# TODO(P4): replace stub with OIDC JWT + role verifier.
async def current_user() -> dict:
    return {"upn": "anonymous@local", "role": "admin"}


def require_editor(user: dict = Depends(current_user)) -> dict:
    # TODO(P4): enforce role check — currently returns user regardless.
    return user
