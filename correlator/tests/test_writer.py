from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from correlator.pipeline.windower import WindowedFlow
from correlator.pipeline.writer import Writer


def _wf() -> WindowedFlow:
    return WindowedFlow(
        bucket_start=datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC),
        window_s=5,
        src_ip="10.0.0.1",
        dst_ip="1.1.1.1",
        dst_port=443,
        proto=6,
        bytes=100,
        packets=2,
        flow_count=1,
        app_id=None,
        fqdn=None,
        action="allow",
    )


@pytest.mark.asyncio
async def test_writer_flushes_on_batch_size() -> None:
    pool = MagicMock()
    conn = AsyncMock()
    conn.copy_records_to_table = AsyncMock()
    # async context manager on pool.acquire()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = None

    q: asyncio.Queue = asyncio.Queue()
    w = Writer(inp=q, pool=pool, batch_size=2, flush_ms=10_000)
    for _ in range(2):
        await q.put(_wf())
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.1)
    task.cancel()

    conn.copy_records_to_table.assert_awaited()
    _args, kwargs = conn.copy_records_to_table.call_args
    assert kwargs["table_name"] == "flows"
    assert len(kwargs["records"]) == 2


@pytest.mark.asyncio
async def test_writer_flushes_on_timer() -> None:
    pool = MagicMock()
    conn = AsyncMock()
    conn.copy_records_to_table = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = None

    q: asyncio.Queue = asyncio.Queue()
    w = Writer(inp=q, pool=pool, batch_size=1000, flush_ms=100)
    await q.put(_wf())
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.25)
    task.cancel()

    conn.copy_records_to_table.assert_awaited()
