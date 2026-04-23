from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from ztna_common.event_types import FlowEvent, IdentityEvent


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(repr(o))


def _jsonify_flow(event: FlowEvent) -> str:
    return json.dumps(event, default=_default, separators=(",", ":"))


def _jsonify_identity(event: IdentityEvent) -> str:
    return json.dumps(event, default=_default, separators=(",", ":"))


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
            self._buf.append(_jsonify_flow(event))
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


class RedisStreamProducer:
    """Lightweight per-event publisher for identity events.

    Identity events are lower-rate than flows, so we skip the batching machinery
    of RedisFlowPublisher and XADD directly. Closed via ``aclose()``.
    """

    def __init__(
        self,
        redis_url: str,
        stream: str,
        *,
        maxlen_approx: int | None = 1_000_000,
    ) -> None:
        self._redis: Redis = Redis.from_url(redis_url, decode_responses=True)
        self._stream = stream
        self._maxlen = maxlen_approx

    async def xadd(self, event: IdentityEvent) -> None:
        payload = _jsonify_identity(event)
        try:
            if self._maxlen is not None:
                await self._redis.xadd(
                    self._stream, {"event": payload}, maxlen=self._maxlen, approximate=True
                )
            else:
                await self._redis.xadd(self._stream, {"event": payload})
        except Exception as exc:
            logger.warning("redis XADD identity failed: {}", exc)
            raise

    async def aclose(self) -> None:
        await self._redis.aclose()
