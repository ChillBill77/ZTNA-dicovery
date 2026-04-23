from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from correlator.pipeline.windower import FlowWindower, WindowedFlow


def _ev(t: datetime, src: str = "10.0.0.1", dst: str = "1.1.1.1",
        port: int = 443, proto: int = 6, b: int = 100, p: int = 1) -> dict:
    return {
        "ts": t, "src_ip": src, "src_port": 1234, "dst_ip": dst, "dst_port": port,
        "proto": proto, "bytes": b, "packets": p, "action": "allow",
        "fqdn": None, "app_id": None, "source": "palo_alto", "raw_id": None,
    }


@pytest.mark.asyncio
async def test_same_bucket_aggregates() -> None:
    inp: asyncio.Queue = asyncio.Queue()
    out: asyncio.Queue = asyncio.Queue()
    w = FlowWindower(inp=inp, out=out, window_s=5)

    t = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    await inp.put(_ev(t, b=100, p=2))
    await inp.put(_ev(t + timedelta(seconds=1), b=200, p=3))
    # Advance past the window boundary to flush.
    await inp.put(_ev(t + timedelta(seconds=6), b=1, p=1))

    task = asyncio.create_task(w.run())
    wf1 = await asyncio.wait_for(out.get(), timeout=1.0)
    task.cancel()
    assert isinstance(wf1, WindowedFlow)
    assert wf1.bytes == 300 and wf1.packets == 5 and wf1.flow_count == 2
    assert wf1.bucket_start == t


@pytest.mark.asyncio
async def test_distinct_keys_emit_separately() -> None:
    inp: asyncio.Queue = asyncio.Queue()
    out: asyncio.Queue = asyncio.Queue()
    w = FlowWindower(inp=inp, out=out, window_s=5)
    t = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)

    await inp.put(_ev(t, dst="1.1.1.1"))
    await inp.put(_ev(t, dst="2.2.2.2"))
    await inp.put(_ev(t + timedelta(seconds=6)))

    task = asyncio.create_task(w.run())
    wf1 = await asyncio.wait_for(out.get(), timeout=1.0)
    wf2 = await asyncio.wait_for(out.get(), timeout=1.0)
    task.cancel()
    dsts = {wf1.dst_ip, wf2.dst_ip}
    assert dsts == {"1.1.1.1", "2.2.2.2"}


@pytest.mark.asyncio
async def test_idle_flush_on_timer() -> None:
    """If no event arrives after the window closes, we still flush existing
    buckets on a tick (every ~1s) so live dashboards don't stall."""
    inp: asyncio.Queue = asyncio.Queue()
    out: asyncio.Queue = asyncio.Queue()
    w = FlowWindower(inp=inp, out=out, window_s=1, tick_s=0.1)

    t = datetime.now(UTC)
    await inp.put(_ev(t))
    task = asyncio.create_task(w.run())
    wf = await asyncio.wait_for(out.get(), timeout=3.0)
    task.cancel()
    assert wf.flow_count == 1
