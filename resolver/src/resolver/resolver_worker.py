from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger
from redis.asyncio import Redis

from resolver.saas_matcher import SaasMatcher, SaasRow

PgUpsert = Callable[[str, str | None, str | None], Awaitable[None]]
# (dst_ip, ptr, source) → upsert into dns_cache


class _TokenBucket:
    def __init__(self, rate_per_s: float) -> None:
        self._rate = rate_per_s
        self._capacity = max(1.0, rate_per_s)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._capacity, self._tokens + (now - self._last) * self._rate
            )
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= 1.0


@dataclass
class ResolverWorker:
    redis: Redis
    dns_resolver: object            # `asyncio.DefaultResolver()` in prod
    saas: SaasMatcher
    pg_upsert: PgUpsert
    rate_per_s: float = 50.0
    ptr_ttl_s: int = 3600
    saas_ttl_s: int = 3600
    _bucket: _TokenBucket = field(init=False)

    def __post_init__(self) -> None:
        self._bucket = _TokenBucket(self.rate_per_s)

    async def process_one(self, ip: str) -> None:
        cached = await self.redis.get(f"dns:ptr:{ip}")
        if cached is not None:
            return
        await self._bucket.take()
        try:
            info = await self.dns_resolver.gethostbyaddr(ip)  # type: ignore[attr-defined]
            name = info.name or ""
        except Exception as exc:  # noqa: BLE001 - DNS failures expected
            logger.debug("PTR lookup failed for {}: {}", ip, exc)
            name = ""
        await self.redis.set(f"dns:ptr:{ip}", name, ex=self.ptr_ttl_s)
        await self.pg_upsert(ip, name or None, "ptr")
        if name:
            row: SaasRow | None = self.saas.match(name)
            if row is not None:
                await self.redis.set(f"dns:saas:{ip}", str(row.id), ex=self.saas_ttl_s)

    async def run_loop(self, queue_key: str = "dns:unresolved") -> None:
        while True:
            item = await self.redis.blpop([queue_key], timeout=5)  # type: ignore[arg-type]
            if item is None:
                continue
            _k, ip = item
            try:
                await self.process_one(ip)
            except Exception as exc:  # noqa: BLE001
                logger.warning("resolver error for {}: {}", ip, exc)
