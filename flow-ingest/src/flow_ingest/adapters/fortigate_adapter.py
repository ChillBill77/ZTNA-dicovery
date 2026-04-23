from __future__ import annotations

import re
import shlex
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from loguru import logger

from flow_ingest.adapters.base import FlowAdapter, FlowEvent
from flow_ingest.publisher import RedisFlowPublisher
from flow_ingest.syslog_receiver import SyslogReceiver

_PRI_PREFIX = re.compile(r"^<\d+>")


def _kv(line: str) -> dict[str, str]:
    line = _PRI_PREFIX.sub("", line).strip()
    # shlex handles quoted values correctly ("foo=bar baz")
    tokens = shlex.split(line, posix=True)
    out: dict[str, str] = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


@dataclass
class FortiGateAdapter(FlowAdapter):
    receiver: SyslogReceiver
    publisher: RedisFlowPublisher
    peer_allowlist: set[str] | None = None
    name: ClassVar[str] = "fortigate"

    @staticmethod
    def parse_line(line: str) -> FlowEvent | None:
        try:
            kv = _kv(line)
        except ValueError:
            return None
        if kv.get("type") != "traffic":
            return None
        if kv.get("subtype") != "forward":
            return None
        if kv.get("status") != "close":
            return None
        try:
            return FlowEvent(
                ts=datetime.now(UTC),
                src_ip=kv["srcip"],
                src_port=int(kv.get("srcport", 0)),
                dst_ip=kv["dstip"],
                dst_port=int(kv.get("dstport", 0)),
                proto=int(kv.get("proto", 0)),
                bytes=int(kv.get("sentbyte", 0)) + int(kv.get("rcvdbyte", 0)),
                packets=int(kv.get("sentpkt", 0)) + int(kv.get("rcvdpkt", 0)),
                action=kv.get("action", "close"),
                fqdn=kv.get("hostname") or None,
                app_id=kv.get("app") or None,
                source=FortiGateAdapter.name,
                raw_id=kv.get("logid"),
            )
        except (KeyError, ValueError):
            return None

    async def run(self) -> AsyncIterator[FlowEvent]:
        while True:
            peer, raw = await self.receiver.queue.get()
            if self.peer_allowlist and peer not in self.peer_allowlist:
                continue
            try:
                ev = self.parse_line(raw)
            except Exception as exc:
                logger.debug("fortigate parse error: {}", exc)
                continue
            if ev is None:
                continue
            await self.publisher.publish(ev)
            yield ev

    def healthcheck(self) -> dict[str, object]:
        return {"name": self.name, "queued": self.receiver.queue.qsize()}
