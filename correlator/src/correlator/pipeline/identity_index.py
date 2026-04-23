from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from intervaltree import IntervalTree


@dataclass(frozen=True)
class Binding:
    user_upn: str
    confidence: int
    source: str
    t_start: datetime


class IdentityIndex:
    """Per-src_ip ``IntervalTree`` resolving ``(src_ip, at) → Binding``.

    Resolution rule (spec §6.2):
      1. Collect all intervals containing ``at``.
      2. Pick the binding with the highest confidence.
      3. Tiebreak on the most recent ``t_start``.
      4. If none → return ``None``.

    Stop events (``event_type == 'nac-auth-stop'`` or ``ttl_seconds == 0``)
    remove all prior bindings for that user on that ``src_ip``. Expired
    intervals are evicted lazily on ``resolve`` probes.
    """

    def __init__(self) -> None:
        self._trees: dict[str, IntervalTree] = {}

    @staticmethod
    def _ts(ev: dict[str, Any]) -> datetime:
        raw = ev["ts"]
        if isinstance(raw, str):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return raw  # type: ignore[no-any-return]

    def insert(self, ev: dict[str, Any]) -> None:
        ip = ev["src_ip"]
        t = self._ts(ev)
        if (
            ev.get("event_type") == "nac-auth-stop"
            or int(ev.get("ttl_seconds", 0)) == 0
        ):
            self._invalidate(ip, ev.get("user_upn"))
            return
        end = t + timedelta(seconds=int(ev["ttl_seconds"]))
        tree = self._trees.setdefault(ip, IntervalTree())
        tree.addi(
            t.timestamp(),
            end.timestamp(),
            Binding(
                user_upn=ev["user_upn"],
                confidence=int(ev["confidence"]),
                source=ev["source"],
                t_start=t,
            ),
        )

    def _invalidate(self, ip: str, user: str | None) -> None:
        tree = self._trees.get(ip)
        if not tree:
            return
        if user is None:
            tree.clear()
            return
        for iv in list(tree):
            if iv.data.user_upn == user:
                tree.remove(iv)

    def resolve(self, ip: str, at: datetime) -> dict[str, Any] | None:
        tree = self._trees.get(ip)
        if not tree:
            return None
        now_ts = at.timestamp()
        # Lazy eviction of expired intervals.
        for iv in list(tree):
            if iv.end <= now_ts:
                tree.remove(iv)
        if not tree:
            self._trees.pop(ip, None)
            return None
        hits = sorted(
            tree[now_ts],
            key=lambda i: (-i.data.confidence, -i.data.t_start.timestamp()),
        )
        if not hits:
            return None
        b = hits[0].data
        return {
            "user_upn": b.user_upn,
            "confidence": b.confidence,
            "source": b.source,
            "t_start": b.t_start,
            "ttl_remaining": int(hits[0].end - now_ts),
        }

    def size(self) -> int:
        return sum(len(t) for t in self._trees.values())
