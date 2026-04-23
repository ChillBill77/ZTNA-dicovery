"""End-to-end P2 pipeline integration test.

Drives a recorded PAN syslog fixture through:
  syslog UDP :5514 → flow-ingest → Redis flows.raw → correlator → flows table
                                                              → /ws/sankey → assertion

Also tests that an application override inserted via POST /api/applications
propagates to the next tick's SankeyDelta.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from pathlib import Path

import pytest
import websockets

from .replay import replay_udp

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_pan_flows_reach_db_and_websocket(
    compose_stack,
    fixture_path: Path,
) -> None:
    # 1. Replay fixture
    path = fixture_path / "palo_alto" / "traffic_end_sample.csv"
    sent = await replay_udp(path=path, host="localhost", port=5514)
    assert sent > 0

    # 2. Wait up to 15 s for flows to appear in DB
    deadline = time.monotonic() + 15
    count = 0
    while time.monotonic() < deadline:
        req = urllib.request.Request("http://localhost:8000/api/flows/raw?limit=100")
        with urllib.request.urlopen(req, timeout=3) as r:
            body = json.loads(r.read())
        count = len(body["items"])
        if count > 0:
            break
        await asyncio.sleep(1)
    assert count > 0, "no flows landed in DB within 15 s"

    # 3. Subscribe to /ws/sankey and wait for a delta
    async with websockets.connect("ws://localhost:8000/ws/sankey") as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        delta = json.loads(msg)
        assert "links" in delta
        assert "lossy" in delta
        assert "window_s" in delta


@pytest.mark.asyncio
async def test_application_override_propagates_within_two_ticks(
    compose_stack,
    fixture_path: Path,
) -> None:
    # Seed flows first
    path = fixture_path / "palo_alto" / "traffic_end_sample.csv"
    await replay_udp(path=path, host="localhost", port=5514)
    await asyncio.sleep(2)

    # Insert an override for a specific dst_cidr present in the fixture
    override = {
        "name": "INTEGRATION-TEST-OVERRIDE",
        "dst_cidr": "198.51.100.10/32",
        "dst_port_min": 443,
        "dst_port_max": 443,
        "proto": 6,
        "priority": 1000,
        "owner": "integration",
    }
    req = urllib.request.Request(
        "http://localhost:8000/api/applications",
        method="POST",
        data=json.dumps(override).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        assert r.status == 201

    # Replay again to generate new window activity
    await replay_udp(path=path, host="localhost", port=5514)

    # WS should see our label within 3 ticks (~15 s)
    async with websockets.connect("ws://localhost:8000/ws/sankey") as ws:
        for _ in range(3):
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            delta = json.loads(msg)
            labels = {n["label"] for n in delta.get("nodes_right", [])}
            if "INTEGRATION-TEST-OVERRIDE" in labels:
                return
        pytest.fail("override did not propagate within 3 ticks")
