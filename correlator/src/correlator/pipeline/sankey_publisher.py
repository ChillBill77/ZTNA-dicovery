from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from correlator.pipeline.app_resolver import AppCandidate
from correlator.pipeline.group_aggregator import GroupAggregator
from correlator.pipeline.group_index import GroupIndex
from correlator.pipeline.metrics import (
    CORRELATOR_LCD_MISS,
    CORRELATOR_UNKNOWN_USER_RATIO,
)


@dataclass
class LabelledFlow:
    bucket_start: datetime
    window_s: int
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    flow_count: int
    candidate: AppCandidate
    lossy: bool = False
    dropped_count: int = 0
    # Identity enrichment (P3 followup). Populated by ``Enricher`` after the
    # AppResolver has produced ``candidate``. ``user_upn == "unknown"`` and
    # empty ``groups`` when no binding exists for (src_ip, bucket_start).
    user_upn: str = "unknown"
    groups: frozenset[str] = field(default_factory=frozenset)


@dataclass
class SankeyPublisher:
    inp: asyncio.Queue[LabelledFlow]
    redis: Redis
    channel: str = "sankey.live"
    aggregator: GroupAggregator | None = None
    group_index: GroupIndex | None = None
    # One of "group" | "user" | "src_ip" | "app". "app" preserves the legacy
    # P2 (src_ip → app_label) behavior when no aggregator is configured.
    group_by: str = "group"

    async def run(self) -> None:
        current_bucket: datetime | None = None
        pending: list[LabelledFlow] = []
        while True:
            lf: LabelledFlow = await self.inp.get()
            if current_bucket is None:
                current_bucket = lf.bucket_start
            if lf.bucket_start > current_bucket:
                await self._publish(current_bucket, pending)
                pending = []
                current_bucket = lf.bucket_start
            pending.append(lf)

    async def _publish(self, bucket: datetime, flows: list[LabelledFlow]) -> None:
        if not flows:
            return
        if self.aggregator is None or self.group_by == "app":
            delta = self._build_legacy_delta(bucket, flows)
        else:
            delta = self._build_group_delta(bucket, flows)
        serialized = json.dumps(delta)
        try:
            # Store latest delta for mode=live REST reads.
            await self.redis.set("sankey.last", serialized)
            await self.redis.publish(self.channel, serialized)
        except Exception as exc:
            logger.warning("sankey publish failed: {}", exc)

    def _build_legacy_delta(
        self, bucket: datetime, flows: list[LabelledFlow]
    ) -> dict[str, Any]:
        links: dict[tuple[str, str], dict[str, Any]] = {}
        nodes_left: dict[str, dict[str, Any]] = {}
        nodes_right: dict[str, dict[str, Any]] = {}
        lossy = False
        dropped = 0
        for f in flows:
            left = f"ip:{f.src_ip}"
            right = f"app:{f.candidate.label}"
            key = (left, right)
            link = links.setdefault(
                key,
                {
                    "src": left,
                    "dst": right,
                    "bytes": 0,
                    "flows": 0,
                    "users": 0,
                },
            )
            link["bytes"] += f.bytes
            link["flows"] += f.flow_count
            nodes_left.setdefault(left, {"id": left, "label": f.src_ip, "size": 0})
            nodes_left[left]["size"] += 1
            nodes_right.setdefault(
                right,
                {
                    "id": right,
                    "label": f.candidate.label,
                    "kind": f.candidate.label_kind,
                },
            )
            lossy = lossy or f.lossy
            dropped += f.dropped_count
        return {
            "ts": bucket.isoformat(),
            "window_s": flows[0].window_s,
            "nodes_left": list(nodes_left.values()),
            "nodes_right": list(nodes_right.values()),
            "links": list(links.values()),
            "lossy": lossy,
            "dropped_count": dropped,
        }

    def _build_group_delta(
        self, bucket: datetime, flows: list[LabelledFlow]
    ) -> dict[str, Any]:
        # ``aggregator``/``group_index`` are guaranteed non-None when group-mode
        # is active (see ``_publish``). Bind locally to please mypy without an
        # extra runtime branch.
        assert self.aggregator is not None
        agg = self.aggregator
        group_sizes: dict[str, int] = (
            self.group_index.group_sizes if self.group_index is not None else {}
        )

        rows: list[dict[str, Any]] = []
        right_kind: dict[str, str] = {}
        right_label: dict[str, str] = {}
        lossy = False
        dropped = 0
        unknown_count = 0
        total = 0
        for f in flows:
            dst = f"app:{f.candidate.label}"
            rows.append(
                {
                    "user_upn": f.user_upn,
                    "groups": f.groups,
                    "dst": dst,
                    "src_ip": f.src_ip,
                    "bytes": f.bytes,
                    "flows": f.flow_count,
                }
            )
            # Preserve right-side kind/label across the window (last-write-wins
            # is fine: the candidate.label_kind is deterministic per dst).
            right_kind[dst] = f.candidate.label_kind
            right_label[dst] = f.candidate.label
            lossy = lossy or f.lossy
            dropped += f.dropped_count
            total += 1
            if f.user_upn == "unknown":
                unknown_count += 1

        links = agg.aggregate(rows, group_sizes=group_sizes, group_by=self.group_by)

        # Heuristic LCD-miss counter: in "group" mode, an LCD hit yields a
        # group-id label; a miss falls back to per-user, where labels are UPNs
        # (typically containing '@'). Skip the synthetic "unknown" strand.
        if self.group_by == "group":
            for link in links:
                src = link["src"]
                if src != "unknown" and "@" in src:
                    CORRELATOR_LCD_MISS.inc()

        if total > 0:
            CORRELATOR_UNKNOWN_USER_RATIO.set(unknown_count / total)

        nodes_left = self._build_left_nodes(links)
        nodes_right = [
            {"id": dst, "label": right_label[dst], "kind": right_kind[dst]}
            for dst in sorted({link["dst"] for link in links})
            if dst in right_label
        ]
        return {
            "ts": bucket.isoformat(),
            "window_s": flows[0].window_s,
            "nodes_left": nodes_left,
            "nodes_right": nodes_right,
            "links": links,
            "lossy": lossy,
            "dropped_count": dropped,
        }

    def _build_left_nodes(
        self, links: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for link in links:
            src = link["src"]
            if src in seen:
                continue
            if self.group_by == "group" and self.group_index is not None and src != "unknown":
                size = self.group_index.size_of(src)
            else:
                size = 0
            seen[src] = {"id": src, "label": src, "size": size}
        return list(seen.values())
