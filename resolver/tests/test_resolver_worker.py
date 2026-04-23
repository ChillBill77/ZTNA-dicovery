from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from resolver.resolver_worker import ResolverWorker
from resolver.saas_matcher import SaasMatcher, SaasRow


class SimpleAddrInfo:
    def __init__(self, name: str) -> None:
        self.name = name


@pytest.mark.asyncio
async def test_cache_hit_skips_dns() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis.set("dns:ptr:8.8.8.8", "dns.google", ex=60)
    mock_resolver = AsyncMock()

    w = ResolverWorker(
        redis=redis,
        dns_resolver=mock_resolver,
        saas=SaasMatcher([]),
        pg_upsert=AsyncMock(),
        rate_per_s=100,
    )

    await w.process_one("8.8.8.8")
    mock_resolver.gethostbyaddr.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_miss_does_lookup_and_caches() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.return_value = SimpleAddrInfo(name="dns.google")
    pg = AsyncMock()

    w = ResolverWorker(
        redis=redis,
        dns_resolver=mock_resolver,
        saas=SaasMatcher([]),
        pg_upsert=pg,
        rate_per_s=100,
    )
    await w.process_one("8.8.8.8")

    assert await redis.get("dns:ptr:8.8.8.8") == "dns.google"
    pg.assert_awaited_once()
    args, _ = pg.call_args
    assert args[0] == "8.8.8.8" and args[1] == "dns.google"


@pytest.mark.asyncio
async def test_nxdomain_caches_empty() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.side_effect = OSError("NXDOMAIN")

    w = ResolverWorker(
        redis=redis,
        dns_resolver=mock_resolver,
        saas=SaasMatcher([]),
        pg_upsert=AsyncMock(),
        rate_per_s=100,
    )
    await w.process_one("192.0.2.1")

    # Empty string sentinel; consumers treat "" as NXDOMAIN.
    assert await redis.get("dns:ptr:192.0.2.1") == ""


@pytest.mark.asyncio
async def test_saas_match_cached() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.return_value = SimpleAddrInfo(name="tenant.outlook.office365.com")

    saas = SaasMatcher(
        [
            SaasRow(id=42, name="M365", pattern=".office365.com", priority=100),
        ]
    )
    w = ResolverWorker(
        redis=redis,
        dns_resolver=mock_resolver,
        saas=saas,
        pg_upsert=AsyncMock(),
        rate_per_s=100,
    )
    await w.process_one("52.97.1.1")

    assert await redis.get("dns:saas:52.97.1.1") == "42"


@pytest.mark.asyncio
async def test_rate_limit_enforced() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.return_value = SimpleAddrInfo(name="x.example.com")

    w = ResolverWorker(
        redis=redis,
        dns_resolver=mock_resolver,
        saas=SaasMatcher([]),
        pg_upsert=AsyncMock(),
        rate_per_s=2,  # 2 qps
    )

    start = asyncio.get_running_loop().time()
    await w.process_one("10.0.0.1")
    await w.process_one("10.0.0.2")
    await w.process_one("10.0.0.3")  # must wait for bucket to refill
    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed >= 0.4  # 3rd call waits ~500ms
