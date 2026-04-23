from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest
from correlator.pipeline.app_resolver import AppCandidate
from correlator.pipeline.sankey_publisher import LabelledFlow, SankeyPublisher


@pytest.mark.asyncio
async def test_publishes_delta_on_window_close() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    q: asyncio.Queue = asyncio.Queue()
    p = SankeyPublisher(inp=q, redis=redis, channel="sankey.live")

    t = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    await q.put(
        LabelledFlow(
            bucket_start=t,
            window_s=5,
            src_ip="10.0.0.1",
            dst_ip="52.97.1.1",
            dst_port=443,
            proto=6,
            bytes=1000,
            packets=10,
            flow_count=3,
            candidate=AppCandidate(label_kind="saas", label="M365", app_id=1),
            lossy=False,
            dropped_count=0,
        )
    )
    await q.put(
        LabelledFlow(
            bucket_start=t,
            window_s=5,
            src_ip="10.0.0.2",
            dst_ip="52.97.1.1",
            dst_port=443,
            proto=6,
            bytes=500,
            packets=4,
            flow_count=1,
            candidate=AppCandidate(label_kind="saas", label="M365", app_id=1),
            lossy=True,
            dropped_count=2,
        )
    )

    pub = asyncio.create_task(p.run())

    async with redis.pubsub() as sub:
        await sub.subscribe("sankey.live")
        # drain subscribe confirmation
        await sub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        # advance with a sentinel that closes the window
        await q.put(
            LabelledFlow(
                bucket_start=t.replace(minute=13),
                window_s=5,
                src_ip="10.0.0.9",
                dst_ip="1.1.1.1",
                dst_port=443,
                proto=6,
                bytes=1,
                packets=1,
                flow_count=1,
                candidate=AppCandidate(label_kind="raw", label="1.1.1.1:443"),
                lossy=False,
                dropped_count=0,
            )
        )
        msg = await sub.get_message(ignore_subscribe_messages=True, timeout=2.0)
        pub.cancel()

    assert msg is not None
    delta = json.loads(msg["data"])
    assert delta["window_s"] == 5
    links = delta["links"]
    assert any(
        l["src"] == "ip:10.0.0.1" and l["dst"] == "app:M365" and l["bytes"] == 1000 for l in links
    )
    assert any(l["src"] == "ip:10.0.0.2" for l in links)
    assert delta["lossy"] is True
    assert delta["dropped_count"] == 2
