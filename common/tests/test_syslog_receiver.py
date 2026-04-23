from __future__ import annotations

import asyncio

import pytest
from ztna_common.syslog_receiver import SyslogReceiver


@pytest.mark.asyncio
async def test_udp_receives_single_datagram() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=128)
    await rx.start()
    try:
        port = rx.udp_port
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=("127.0.0.1", port),
        )
        transport.sendto(b"hello-world\n")
        peer, line = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
        assert line == "hello-world"
        assert peer == "127.0.0.1"
        transport.close()
    finally:
        await rx.stop()


@pytest.mark.asyncio
async def test_tcp_newline_framing() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=128)
    await rx.start()
    try:
        r, w = await asyncio.open_connection("127.0.0.1", rx.tcp_port)
        w.write(b"line-a\nline-b\n")
        await w.drain()
        lines: list[str] = []
        for _ in range(2):
            _peer, raw = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
            lines.append(raw)
        assert lines == ["line-a", "line-b"]
        w.close()
        await w.wait_closed()
    finally:
        await rx.stop()


@pytest.mark.asyncio
async def test_tcp_octet_counting() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=128)
    await rx.start()
    try:
        r, w = await asyncio.open_connection("127.0.0.1", rx.tcp_port)
        w.write(b"6 abcdef5 12345")
        await w.drain()
        _peer, a = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
        _peer, b = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
        assert a == "abcdef"
        assert b == "12345"
        w.close()
        await w.wait_closed()
    finally:
        await rx.stop()


@pytest.mark.asyncio
async def test_backpressure_drops_oldest_and_counts() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=2)
    await rx.start()
    try:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=("127.0.0.1", rx.udp_port),
        )
        for i in range(5):
            transport.sendto(f"m{i}".encode())
        await asyncio.sleep(0.1)
        # Queue keeps at most 2 elements; newest survive.
        items = []
        while not rx.queue.empty():
            items.append(rx.queue.get_nowait()[1])
        assert len(items) == 2
        assert rx.backpressure_drops >= 3
        transport.close()
    finally:
        await rx.stop()
