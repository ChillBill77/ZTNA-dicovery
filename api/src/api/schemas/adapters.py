from __future__ import annotations

from pydantic import BaseModel


class AdapterHealth(BaseModel):
    name: str
    kind: str  # 'flow' | 'identity'
    enabled: bool
    events_per_sec: float = 0.0
    queue_depth: int = 0
    last_event_ts: str | None = None


class Stats(BaseModel):
    flows_per_sec: float = 0.0
    unknown_user_ratio: float = 0.0
    redis_lag_ms: float = 0.0
    lossy_windows_total: int = 0
    # Seconds since the most recent user_groups refresh; None if the sync has
    # never run (or its service is offline). Front-end alert at > 48h.
    group_sync_age_seconds: float | None = None
