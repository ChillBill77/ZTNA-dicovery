from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass

import asyncpg
import uvloop
from loguru import logger
from redis.asyncio import Redis

from resolver.resolver_worker import ResolverWorker
from resolver.saas_matcher import SaasMatcher, SaasRow
from resolver.settings import ResolverSettings


@dataclass
class _PtrResult:
    name: str


class _StdlibPtrResolver:
    """Minimal async wrapper around ``socket.gethostbyaddr`` via the default
    executor. Sufficient for P2; P4 swaps to aiodns for per-query timeouts."""

    async def gethostbyaddr(self, ip: str) -> _PtrResult:
        loop = asyncio.get_running_loop()
        hostname, _aliases, _addrs = await loop.run_in_executor(None, socket.gethostbyaddr, ip)
        return _PtrResult(name=hostname)


async def _load_saas(pool: asyncpg.Pool) -> SaasMatcher:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, fqdn_pattern AS pattern, priority FROM saas_catalog"
        )
    return SaasMatcher([SaasRow(**dict(r)) for r in rows])


async def _pg_upsert_factory(pool: asyncpg.Pool):
    async def _upsert(dst_ip: str, ptr: str | None, source: str | None) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dns_cache (dst_ip, ptr, resolved_at, source)
                VALUES ($1, $2, now(), COALESCE($3, 'ptr'))
                ON CONFLICT (dst_ip) DO UPDATE
                  SET ptr = EXCLUDED.ptr,
                      resolved_at = EXCLUDED.resolved_at,
                      source = EXCLUDED.source;
                """,
                dst_ip,
                ptr,
                source,
            )

    return _upsert


async def _run(settings: ResolverSettings) -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    pool = await asyncpg.create_pool(
        _as_asyncpg_dsn(settings.database_url),
        min_size=1,
        max_size=4,
    )
    saas = await _load_saas(pool)
    pg_upsert = await _pg_upsert_factory(pool)
    resolver_inst = _StdlibPtrResolver()

    worker = ResolverWorker(
        redis=redis,
        dns_resolver=resolver_inst,
        saas=saas,
        pg_upsert=pg_upsert,
        rate_per_s=settings.rate_per_s,
        ptr_ttl_s=settings.ptr_ttl_s,
        saas_ttl_s=settings.saas_ttl_s,
    )
    logger.info("resolver worker starting at {} qps", settings.rate_per_s)
    await worker.run_loop()


def _as_asyncpg_dsn(url: str) -> str:
    # asyncpg only understands postgresql://; strip SQLAlchemy driver suffix.
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def main() -> None:
    uvloop.install()
    asyncio.run(_run(ResolverSettings()))


if __name__ == "__main__":
    main()
