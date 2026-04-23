from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class IdentityService:
    """Resolves (src_ip, at) → binding by querying the identity_events table.

    The correlator maintains an in-memory ``IdentityIndex`` that exposes the
    same semantics for live traffic (spec §6.2). This service path exists for
    point-in-time queries from the api — especially historical ``at``
    parameters where the in-memory index may have evicted expired intervals.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def resolve(
        self, src_ip: str, at: datetime
    ) -> dict[str, Any] | None:
        sql = text(
            """
            SELECT user_upn, source, confidence, ttl_seconds, time
              FROM identity_events
             WHERE src_ip = :ip::inet
               AND time <= :at
               AND time + (ttl_seconds || ' seconds')::interval >= :at
               AND event_type <> 'nac-auth-stop'
             ORDER BY confidence DESC, time DESC
             LIMIT 1
            """
        )
        row = (await self._db.execute(sql, {"ip": src_ip, "at": at})).mappings().first()
        if not row:
            return None
        groups_result = await self._db.execute(
            text(
                "SELECT group_name FROM user_groups "
                "WHERE user_upn = :u ORDER BY group_name"
            ),
            {"u": row["user_upn"]},
        )
        groups = [g[0] for g in groups_result.all()]
        ttl_remaining = max(
            0,
            int(row["ttl_seconds"] - (at - row["time"]).total_seconds()),
        )
        return {
            "user_upn": row["user_upn"],
            "source": row["source"],
            "confidence": row["confidence"],
            "groups": groups,
            "ttl_remaining": ttl_remaining,
        }
