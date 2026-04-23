from __future__ import annotations

import json

from fastapi import APIRouter

from api.dependencies import redis_client
from api.schemas.adapters import AdapterHealth, Stats

router = APIRouter(tags=["adapters"])


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


@router.get("/api/stats", response_model=Stats)
async def stats() -> Stats:
    redis = redis_client()
    raw = await redis.get("stats.global")
    if raw:
        try:
            return Stats(**json.loads(raw))
        except Exception:
            pass
    return Stats()
