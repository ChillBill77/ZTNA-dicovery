from __future__ import annotations

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
from ztna_common.event_types import FlowEvent, IdentityEvent
from ztna_common.redis_bus import RedisFlowPublisher, RedisStreamProducer


def _flow(**over: object) -> FlowEvent:
    base: FlowEvent = {
        "ts": datetime.now(UTC),
        "src_ip": "10.0.0.1",
        "src_port": 33000,
        "dst_ip": "1.1.1.1",
        "dst_port": 443,
        "proto": 6,
        "bytes": 100,
        "packets": 2,
        "action": "allow",
        "fqdn": None,
        "app_id": None,
        "source": "palo_alto",
        "raw_id": None,
    }
    base.update(over)  # type: ignore[typeddict-item]
    return base


@pytest.mark.asyncio
async def test_flow_publisher_flushes_on_batch() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    pub = RedisFlowPublisher(redis=redis, stream="flows.raw", max_batch=2)
    await pub.publish(_flow())
    await pub.publish(_flow(src_ip="10.0.0.2"))
    # xlen should now be 2
    assert await redis.xlen("flows.raw") == 2
    await redis.aclose()


@pytest.mark.asyncio
async def test_flow_publisher_explicit_flush() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    pub = RedisFlowPublisher(redis=redis, stream="flows.raw", max_batch=100)
    await pub.publish(_flow())
    await pub.flush()
    assert await redis.xlen("flows.raw") == 1
    await redis.aclose()


@pytest.mark.asyncio
async def test_identity_stream_producer_xadd() -> None:
    # RedisStreamProducer builds its own Redis; patch to use fakeredis via URL is
    # not supported, so we inject the fake client directly.
    producer = RedisStreamProducer("redis://localhost:6379/0", stream="identity.events")
    producer._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)  # type: ignore[assignment]
    ev: IdentityEvent = {
        "ts": datetime.now(UTC),
        "src_ip": "10.0.12.34",
        "user_upn": "alice@corp",
        "source": "ad_4624",
        "event_type": "logon",
        "confidence": 90,
        "ttl_seconds": 28800,
        "mac": None,
        "raw_id": None,
    }
    await producer.xadd(ev)
    assert await producer._redis.xlen("identity.events") == 1
    await producer.aclose()
