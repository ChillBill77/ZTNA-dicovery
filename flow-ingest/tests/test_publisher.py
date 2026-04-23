from __future__ import annotations

import json
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from flow_ingest.publisher import RedisFlowPublisher


@pytest.mark.asyncio
async def test_publish_writes_event_to_stream() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    pub = RedisFlowPublisher(redis=redis, stream="flows.raw", max_batch=1)

    await pub.publish({
        "ts": datetime(2026, 4, 22, tzinfo=UTC),
        "src_ip": "10.0.0.1", "src_port": 44321,
        "dst_ip": "52.97.1.1",  "dst_port": 443,
        "proto": 6,
        "bytes": 123, "packets": 2,
        "action": "allow",
        "fqdn": None, "app_id": None,
        "source": "palo_alto",
        "raw_id": "r1",
    })
    await pub.flush()
    entries = await redis.xrange("flows.raw")
    assert len(entries) == 1
    payload = json.loads(entries[0][1]["event"])
    assert payload["src_ip"] == "10.0.0.1"
    assert payload["source"] == "palo_alto"
