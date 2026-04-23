from __future__ import annotations

import ipaddress
import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.cursor import CursorPayload, decode_cursor, encode_cursor
from api.dependencies import db_session, redis_client
from api.schemas.flows import RawFlow, RawFlowsPage
from api.schemas.sankey import SankeyDelta

router = APIRouter(prefix="/api/flows", tags=["flows"])

LIVE_KEY = "sankey.last"


def _filter_links(
    delta: dict[str, Any],
    *,
    src_cidr: str | None,
    dst_app: str | None,
    category: str | None,  # not implemented server-side in P2 — SaaS category match deferred
    proto: int | None,
    deny_only: bool,
    group_filter: set[str] | None = None,
    user_filter: str | None = None,
    exclude_groups: set[str] | None = None,
) -> dict[str, Any]:
    links = delta["links"]
    if src_cidr:
        try:
            net = ipaddress.ip_network(src_cidr, strict=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _in_net(src_id: str) -> bool:
            ip = src_id.removeprefix("ip:")
            try:
                return ipaddress.ip_address(ip) in net
            except ValueError:
                return False

        links = [lk for lk in links if _in_net(lk["src"])]
    if dst_app:
        target = f"app:{dst_app}"
        links = [lk for lk in links if lk["dst"] == target]
    # Identity-aware filters (P3). All operate on the left-node label that the
    # correlator already published — no DB roundtrip here.
    if group_filter:
        # Keep only links whose src label is in the allowed set (or "unknown").
        links = [lk for lk in links if lk["src"] in group_filter or lk["src"] == "unknown"]
    if user_filter:
        links = [lk for lk in links if lk["src"] == user_filter or lk["src"] == "unknown"]
    if exclude_groups:
        links = [lk for lk in links if lk["src"] not in exclude_groups]
    # proto / deny_only filtering is a noop in P2 (not carried on aggregated delta);
    # TODO(P3/P4): enrich SankeyDelta with per-link proto + action rollups.
    return {**delta, "links": links}


def _truncate(delta: dict[str, Any], limit: int) -> dict[str, Any]:
    links = delta["links"]
    total = len(links)
    ranked = sorted(links, key=lambda lk: lk["bytes"], reverse=True)[:limit]
    return {**delta, "links": ranked, "truncated": total > limit, "total_links": total}


@router.get("/sankey", response_model=SankeyDelta)
async def sankey(
    mode: Literal["live", "historical"] = "live",
    limit: int = Query(200, ge=1, le=1000),
    src_cidr: str | None = None,
    dst_app: str | None = None,
    category: str | None = None,
    proto: int | None = None,
    deny_only: bool = False,
    group_by: Literal["src_ip", "app", "group", "user"] = "src_ip",
    group: list[str] = Query(default_factory=list),
    user: str | None = None,
    exclude_groups: str | None = None,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(db_session),
) -> SankeyDelta:
    if mode == "live":
        redis = redis_client()
        raw = await redis.get(LIVE_KEY)
        base = (
            json.loads(raw)
            if raw
            else {
                "ts": datetime.now(UTC).isoformat(),
                "window_s": 5,
                "nodes_left": [],
                "nodes_right": [],
                "links": [],
                "lossy": False,
                "dropped_count": 0,
            }
        )
    else:
        if from_ts is None or to_ts is None:
            raise HTTPException(status_code=400, detail="from/to required for historical")
        result = await session.execute(
            text(
                """
            SELECT src_ip::text AS src_ip, dst_ip::text AS dst_ip, dst_port, proto,
                   sum(bytes) AS bytes, sum(packets) AS packets,
                   sum(flow_count) AS flow_count
            FROM flows_1m
            WHERE bucket >= :from_ts AND bucket < :to_ts
            GROUP BY src_ip, dst_ip, dst_port, proto
            """
            ),
            {"from_ts": from_ts, "to_ts": to_ts},
        )
        rows = result.mappings().all()
        # In P2 the historical path uses raw src_ip → ip:port right-column label.
        links: list[dict[str, Any]] = [
            {
                "src": f"ip:{r['src_ip']}",
                "dst": f"app:{r['dst_ip']}:{r['dst_port']}",
                "bytes": int(r["bytes"]),
                "flows": int(r["flow_count"]),
                "users": 0,
            }
            for r in rows
        ]
        base = {
            "ts": (from_ts or datetime.now(UTC)).isoformat(),
            "window_s": int((to_ts - from_ts).total_seconds()) if from_ts and to_ts else 0,
            "nodes_left": [],
            "nodes_right": [],
            "links": links,
            "lossy": False,
            "dropped_count": 0,
        }

    exclude_set = (
        {g.strip() for g in exclude_groups.split(",") if g.strip()}
        if exclude_groups
        else None
    )
    group_set = {g for g in group if g} or None
    filtered = _filter_links(
        base,
        src_cidr=src_cidr,
        dst_app=dst_app,
        category=category,
        proto=proto,
        deny_only=deny_only,
        group_filter=group_set,
        user_filter=user,
        exclude_groups=exclude_set,
    )
    truncated = _truncate(filtered, limit)
    # Ensure node lists include only referenced ids
    used_left = {lk["src"] for lk in truncated["links"]}
    used_right = {lk["dst"] for lk in truncated["links"]}
    truncated["nodes_left"] = [n for n in truncated.get("nodes_left", []) if n["id"] in used_left]
    truncated["nodes_right"] = [
        n for n in truncated.get("nodes_right", []) if n["id"] in used_right
    ]
    return SankeyDelta(**truncated)


@router.get("/raw", response_model=RawFlowsPage)
async def raw(
    limit: int = Query(500, ge=1, le=5000),
    cursor: str | None = None,
    src_ip: str | None = None,
    dst_ip: str | None = None,
    port: int | None = None,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(db_session),
) -> RawFlowsPage:
    conds: list[str] = []
    params: dict[str, Any] = {"limit": limit + 1}
    if cursor:
        try:
            cur = decode_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conds.append(
            "(time, src_ip, dst_ip, dst_port) < "
            "(:cur_time, :cur_src_ip::inet, :cur_dst_ip::inet, :cur_dst_port)"
        )
        params.update(
            {
                "cur_time": cur.last_time,
                "cur_src_ip": cur.last_src_ip,
                "cur_dst_ip": cur.last_dst_ip,
                "cur_dst_port": cur.last_dst_port,
            }
        )
    if src_ip:
        conds.append("src_ip = :src_ip::inet")
        params["src_ip"] = src_ip
    if dst_ip:
        conds.append("dst_ip = :dst_ip::inet")
        params["dst_ip"] = dst_ip
    if port is not None:
        conds.append("dst_port = :port")
        params["port"] = port
    if from_ts is not None:
        conds.append("time >= :from_ts")
        params["from_ts"] = from_ts
    if to_ts is not None:
        conds.append("time < :to_ts")
        params["to_ts"] = to_ts

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    sql = f"""
        SELECT time, src_ip::text AS src_ip, dst_ip::text AS dst_ip, dst_port,
               proto, bytes, packets, flow_count, source
        FROM flows
        {where}
        ORDER BY time DESC, src_ip DESC, dst_ip DESC, dst_port DESC
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    rows = [dict(r) for r in result.mappings().all()]

    next_cursor: str | None = None
    if len(rows) > limit:
        extra = rows.pop()  # the n+1 row becomes cursor anchor
        next_cursor = encode_cursor(
            CursorPayload(
                last_time=extra["time"],
                last_src_ip=extra["src_ip"],
                last_dst_ip=extra["dst_ip"],
                last_dst_port=extra["dst_port"],
            )
        )

    items = [RawFlow(**r) for r in rows]
    return RawFlowsPage(items=items, next_cursor=next_cursor, total_est=None)
