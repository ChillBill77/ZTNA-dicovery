from __future__ import annotations

from typing import Any

from fastapi import HTTPException


async def current_user() -> dict[str, Any]:
    """Placeholder that denies all callers.

    Replaced in Chunk 2 (Task 1.7) with session-cookie + bearer-token
    resolution. Tests override via ``app.dependency_overrides``.
    """

    raise HTTPException(status_code=401, detail="unauthenticated")
