from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from flow_ingest.adapters.base import FlowEvent


def _jsonify(event: FlowEvent) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(repr(o))

    return json.dumps(event, default=default, separators=(",", ":"))


@dataclass
class RedisFlowPublisher:
    redis: Redis
    stream: str = "flows.raw"
    max_batch: int = 50
    max_wait_ms: int = 100
    maxlen_approx: int | None = 1_000_000  # XADD MAXLEN ~
    _buf: list[str] = field(init=False, default_factory=list)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._buf = []
        self._lock = asyncio.Lock()
        self._timer: asyncio.TimerHandle | None = None

    async def publish(self, event: FlowEvent) -> None:
        async with self._lock:
            self._buf.append(_jsonify(event))
            if len(self._buf) >= self.max_batch:
                await self._flush_locked()

    async def flush(self) -> None:
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._buf:
            return
        pipe = self.redis.pipeline(transaction=False)
        for payload in self._buf:
            if self.maxlen_approx is not None:
                pipe.xadd(
                    self.stream, {"event": payload}, maxlen=self.maxlen_approx, approximate=True
                )
            else:
                pipe.xadd(self.stream, {"event": payload})
        try:
            await pipe.execute()
        except Exception as exc:
            logger.warning("redis XADD failed: {}", exc)
            raise
        finally:
            self._buf.clear()
