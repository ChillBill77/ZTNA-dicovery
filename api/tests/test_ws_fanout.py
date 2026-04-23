from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest

from api.ws_fanout import ClientState, SankeyFanout


@pytest.mark.asyncio
async def test_fanout_dispatches_message_to_matching_client() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fan = SankeyFanout(redis=redis, channel="sankey.live")
    await fan.start()

    received: list[dict] = []

    async def _send(msg: str) -> None:
        received.append(json.loads(msg))

    client = ClientState(send=_send, filters={"dst_app": "M365"})
    fan.add_client(client)

    # Give the subscribe loop a moment to attach before publishing.
    await asyncio.sleep(0.1)
    await redis.publish("sankey.live", json.dumps({
        "ts": "t", "window_s": 5, "nodes_left": [], "nodes_right": [],
        "links": [
            {"src": "ip:10.0.0.1", "dst": "app:M365", "bytes": 1, "flows": 1, "users": 0},
            {"src": "ip:10.0.0.2", "dst": "app:Other", "bytes": 1, "flows": 1, "users": 0},
        ],
        "lossy": False, "dropped_count": 0,
    }))
    await asyncio.sleep(0.2)

    fan.remove_client(client)
    await fan.stop()
    assert len(received) == 1
    assert all(l["dst"] == "app:M365" for l in received[0]["links"])


def test_client_state_filters_src_cidr() -> None:
    client = ClientState(send=lambda _p: None, filters={"src_cidr": "10.0.0.0/24"})
    assert client.matches({"src": "ip:10.0.0.1", "dst": "app:X"}) is True
    assert client.matches({"src": "ip:10.0.1.1", "dst": "app:X"}) is False
