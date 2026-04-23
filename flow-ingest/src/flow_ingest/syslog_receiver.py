from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from loguru import logger

Message = tuple[str, str]  # (peer_ip, line)


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[Message], parent: SyslogReceiver) -> None:
        self._queue = queue
        self._parent = parent

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        line = data.rstrip(b"\r\n").decode("utf-8", errors="replace")
        if not line:
            return
        self._parent._enqueue(addr[0], line)


async def _handle_tcp_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    parent: SyslogReceiver,
) -> None:
    peer = writer.get_extra_info("peername") or ("unknown", 0)
    peer_ip = peer[0]
    buf = b""
    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buf += chunk
            buf = _drain_buffer(buf, peer_ip, parent)
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _drain_buffer(buf: bytes, peer_ip: str, parent: SyslogReceiver) -> bytes:
    while buf:
        # Octet-counting: leading ASCII digits + space + body of that length.
        if buf[:1].isdigit():
            sp = buf.find(b" ")
            if sp == -1:
                return buf
            try:
                length = int(buf[:sp])
            except ValueError:
                length = -1
            if length >= 0 and len(buf) >= sp + 1 + length:
                body = buf[sp + 1 : sp + 1 + length]
                parent._enqueue(peer_ip, body.decode("utf-8", errors="replace"))
                buf = buf[sp + 1 + length :]
                continue
            return buf  # need more bytes
        # Newline framing
        nl = buf.find(b"\n")
        if nl == -1:
            return buf
        line = buf[:nl].rstrip(b"\r")
        if line:
            parent._enqueue(peer_ip, line.decode("utf-8", errors="replace"))
        buf = buf[nl + 1 :]
    return buf


@dataclass
class SyslogReceiver:
    host: str
    port: int
    queue_max: int = 10_000
    queue: asyncio.Queue[Message] = field(init=False)
    backpressure_drops: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.queue = asyncio.Queue(maxsize=self.queue_max)
        self.backpressure_drops = 0
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._tcp_server: asyncio.AbstractServer | None = None
        self.udp_port: int = 0
        self.tcp_port: int = 0

    def _enqueue(self, peer_ip: str, line: str) -> None:
        try:
            self.queue.put_nowait((peer_ip, line))
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = self.queue.get_nowait()
            self.backpressure_drops += 1
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait((peer_ip, line))

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self.queue, self),
            local_addr=(self.host, self.port),
        )
        self._udp_transport = transport
        sock = transport.get_extra_info("socket")
        self.udp_port = sock.getsockname()[1]

        self._tcp_server = await asyncio.start_server(
            lambda r, w: _handle_tcp_client(r, w, self),
            host=self.host,
            port=self.port if self.port else 0,
        )
        self.tcp_port = self._tcp_server.sockets[0].getsockname()[1]
        logger.info(
            "syslog receiver listening udp={}, tcp={}",
            self.udp_port,
            self.tcp_port,
        )

    async def stop(self) -> None:
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
        if self._udp_transport is not None:
            self._udp_transport.close()
