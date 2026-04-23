"""Replay a fixture file into the firewall-syslog entrypoint.

Two transports: UDP via asyncio datagram, TCP via asyncio stream.
Replay rate is configurable; default is "as fast as possible" for tests.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


async def replay_udp(
    *,
    path: Path,
    host: str,
    port: int,
    rate_per_s: float | None = None,
) -> int:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, remote_addr=(host, port)
    )
    try:
        lines = path.read_text().splitlines()
        delay = 1.0 / rate_per_s if rate_per_s else 0.0
        sent = 0
        for line in lines:
            if not line.strip() or line.startswith("#"):
                continue
            transport.sendto(line.encode())
            sent += 1
            if delay:
                await asyncio.sleep(delay)
        return sent
    finally:
        transport.close()


async def replay_tcp(
    *,
    path: Path,
    host: str,
    port: int,
) -> int:
    reader, writer = await asyncio.open_connection(host, port)
    del reader
    try:
        content = path.read_bytes()
        writer.write(content)
        await writer.drain()
        return content.count(b"\n")
    finally:
        writer.close()
        await writer.wait_closed()
