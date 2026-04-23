from __future__ import annotations

import fakeredis.aioredis
import pytest

from correlator.pipeline.app_resolver import (
    AppResolver,
    ManualApp,
    PortDefault,
    SaasEntry,
)


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_manual_match_wins(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(
        manual=[ManualApp(id=1, name="CRM-Prod", cidr="10.100.0.0/16",
                          port_min=None, port_max=None, proto=None, priority=200)],
        saas=[], port_defaults=[],
    )
    cand = await r.resolve(dst_ip="10.100.0.5", dst_port=443, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "manual"
    assert cand.label == "CRM-Prod"


@pytest.mark.asyncio
async def test_firewall_fqdn_matches_saas(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[],
           saas=[SaasEntry(id=1, name="M365", pattern=".office365.com", priority=100)],
           port_defaults=[])
    cand = await r.resolve(dst_ip="52.97.1.1", dst_port=443, proto=6,
                           firewall_fqdn="outlook.office365.com", app_id=None)
    assert cand.label_kind == "saas"
    assert cand.label == "M365"


@pytest.mark.asyncio
async def test_ptr_fallback_via_redis(redis) -> None:
    await redis.set("dns:ptr:8.8.8.8", "dns.google")
    await redis.set("dns:saas:8.8.8.8", "7")
    r = AppResolver(redis=redis)
    r.load(manual=[],
           saas=[SaasEntry(id=7, name="Google DNS", pattern=".google", priority=90)],
           port_defaults=[])
    cand = await r.resolve(dst_ip="8.8.8.8", dst_port=53, proto=17,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "ptr"
    assert cand.label == "Google DNS"


@pytest.mark.asyncio
async def test_port_default_when_no_fqdn(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[], port_defaults=[PortDefault(port=22, proto=6, name="SSH")])
    cand = await r.resolve(dst_ip="10.0.0.99", dst_port=22, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "port"
    assert cand.label == "SSH"


@pytest.mark.asyncio
async def test_raw_fallback(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[], port_defaults=[])
    cand = await r.resolve(dst_ip="198.51.100.1", dst_port=9999, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "raw"
    assert cand.label == "198.51.100.1:9999"


@pytest.mark.asyncio
async def test_missing_ptr_enqueues_for_resolver(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[], port_defaults=[])
    await r.resolve(dst_ip="203.0.113.5", dst_port=443, proto=6,
                    firewall_fqdn=None, app_id=None)
    assert await redis.lpop("dns:unresolved") == "203.0.113.5"


@pytest.mark.asyncio
async def test_reload_replaces_caches(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[ManualApp(id=1, name="Old", cidr="10.0.0.0/8",
                             port_min=None, port_max=None, proto=None, priority=100)],
           saas=[], port_defaults=[])
    r.load(manual=[ManualApp(id=2, name="New", cidr="10.0.0.0/8",
                             port_min=None, port_max=None, proto=None, priority=100)],
           saas=[], port_defaults=[])
    cand = await r.resolve(dst_ip="10.0.0.1", dst_port=443, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label == "New"
