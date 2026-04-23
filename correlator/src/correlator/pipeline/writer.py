from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import asyncpg
from loguru import logger

from correlator.pipeline.windower import WindowedFlow


@dataclass
class Writer:
    inp: asyncio.Queue
    pool: asyncpg.Pool
    batch_size: int = 10_000
    flush_ms: int = 500

    async def _flush(self, rows: list[tuple]) -> None:
        if not rows:
            return
        async with self.pool.acquire() as conn:
            await conn.copy_records_to_table(
                table_name="flows",
                records=rows,
                columns=[
                    "time",
                    "src_ip",
                    "dst_ip",
                    "dst_port",
                    "proto",
                    "bytes",
                    "packets",
                    "flow_count",
                    "source",
                ],
            )

    async def run(self) -> None:
        buf: list[tuple] = []
        deadline = time.monotonic() + self.flush_ms / 1000
        while True:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                wf: WindowedFlow = await asyncio.wait_for(self.inp.get(), timeout=timeout)
                buf.append(
                    (
                        wf.bucket_start,
                        wf.src_ip,
                        wf.dst_ip,
                        wf.dst_port,
                        wf.proto,
                        wf.bytes,
                        wf.packets,
                        wf.flow_count,
                        "correlator",
                    )
                )
                if len(buf) >= self.batch_size:
                    await self._flush_safe(buf)
                    buf = []
                    deadline = time.monotonic() + self.flush_ms / 1000
            except TimeoutError:
                if buf:
                    await self._flush_safe(buf)
                    buf = []
                deadline = time.monotonic() + self.flush_ms / 1000

    async def _flush_safe(self, buf: list[tuple]) -> None:
        try:
            await self._flush(buf)
        except Exception as exc:
            logger.warning("writer flush failed; dropping {} rows: {}", len(buf), exc)
