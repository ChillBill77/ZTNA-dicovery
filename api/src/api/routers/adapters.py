from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.roles import require_role
from api.dependencies import db_session, redis_client
from api.schemas.adapters import AdapterHealth, Stats

router = APIRouter(tags=["adapters"], dependencies=[require_role("viewer")])


@router.get("/api/adapters", response_model=list[AdapterHealth])
async def adapters() -> list[AdapterHealth]:
    redis = redis_client()
    # Each service publishes `adapters.health:<name>` every heartbeat.
    keys = await redis.keys("adapters.health:*")
    out: list[AdapterHealth] = []
    for k in keys:
        raw = await redis.get(k)
        if raw:
            try:
                out.append(AdapterHealth(**json.loads(raw)))
            except Exception:
                continue
    return out


async def _group_sync_age(session: AsyncSession) -> float | None:
    row = (
        await session.execute(
            text("SELECT MAX(refreshed_at) AS latest FROM user_groups")
        )
    ).mappings().first()
    if not row or row["latest"] is None:
        return None
    delta = datetime.now(UTC) - row["latest"]
    return max(0.0, delta.total_seconds())


@router.get("/api/stats", response_model=Stats)
async def stats(session: AsyncSession = Depends(db_session)) -> Stats:
    redis = redis_client()
    raw = await redis.get("stats.global")
    base = Stats()
    if raw:
        try:
            base = Stats(**json.loads(raw))
        except Exception:
            pass
    # Override identity-related field from live DB so operators always see a
    # current value even when the aggregator hasn't published a refresh.
    try:
        base.group_sync_age_seconds = await _group_sync_age(session)
    except Exception:  # noqa: BLE001 — stat is best-effort, never block response
        pass
    return base
