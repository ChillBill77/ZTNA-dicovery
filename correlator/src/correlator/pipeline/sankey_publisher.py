from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from correlator.pipeline.app_resolver import AppCandidate


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


@dataclass
class SankeyPublisher:
    inp: asyncio.Queue[LabelledFlow]
    redis: Redis
    channel: str = "sankey.live"

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
        delta = {
            "ts": bucket.isoformat(),
            "window_s": flows[0].window_s,
            "nodes_left": list(nodes_left.values()),
            "nodes_right": list(nodes_right.values()),
            "links": list(links.values()),
            "lossy": lossy,
            "dropped_count": dropped,
        }
        serialized = json.dumps(delta)
        try:
            # Store latest delta for mode=live REST reads.
            await self.redis.set("sankey.last", serialized)
            await self.redis.publish(self.channel, serialized)
        except Exception as exc:
            logger.warning("sankey publish failed: {}", exc)
