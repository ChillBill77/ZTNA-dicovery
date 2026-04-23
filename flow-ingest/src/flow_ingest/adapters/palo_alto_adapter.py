from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from loguru import logger

from flow_ingest.adapters.base import FlowAdapter, FlowEvent

_PROTO_BY_NAME: dict[str, int] = {"tcp": 6, "udp": 17, "icmp": 1}

# PAN-OS TRAFFIC CSV minimum column count we rely on (bytes + packets are at
# indices 31 and 32; anything shorter isn't a usable TRAFFIC row).
_MIN_PAN_CSV_FIELDS = 32
# Minimum pipe-segments in a LEEF 2.0 envelope before extension fields.
_MIN_LEEF_PIPES = 6
# Index of the generated_time column in PAN-OS TRAFFIC CSV (0-based). Used to
# guard the timestamp lookup against short rows.
_PAN_GENERATED_TIME_IDX = 6


def _proto(val: str) -> int:
    val = val.strip().lower()
    if val in _PROTO_BY_NAME:
        return _PROTO_BY_NAME[val]
    try:
        return int(val)
    except ValueError:
        return 0


@dataclass
class PaloAltoAdapter(FlowAdapter):
    name: ClassVar[str] = "palo_alto"

    @staticmethod
    def parse_line(line: str) -> FlowEvent | None:
        if "LEEF:" in line and "Palo Alto Networks" in line:
            return _parse_leef(line)
        if "TRAFFIC" in line:
            return _parse_csv(line)
        return None

    async def run(self) -> AsyncIterator[FlowEvent]:
        while True:
            peer, raw = await self.receiver.queue.get()
            if self.peer_allowlist and peer not in self.peer_allowlist:
                continue
            try:
                ev = self.parse_line(raw)
            except Exception as exc:
                logger.debug("palo_alto parse error: {}", exc)
                continue
            if ev is None:
                continue
            await self.publisher.publish(ev)
            yield ev

    def healthcheck(self) -> dict[str, object]:
        return {"name": self.name, "queued": self.receiver.queue.qsize()}


def _parse_csv(line: str) -> FlowEvent | None:
    # Syslog prefix may precede the CSV payload: `<14>Apr 22 ... : <csv...>`.
    payload = line.split(": ", 1)[-1] if ": " in line else line
    reader = csv.reader(io.StringIO(payload))
    fields = next(reader, None)
    if fields is None or len(fields) < _MIN_PAN_CSV_FIELDS or fields[3] != "TRAFFIC":
        return None
    if fields[4] != "end":
        return None
    try:
        return FlowEvent(
            ts=(_ts(fields[6]) if len(fields) > _PAN_GENERATED_TIME_IDX else datetime.now(UTC)),
            src_ip=fields[7],
            src_port=int(fields[24] or 0),
            dst_ip=fields[8],
            dst_port=int(fields[25] or 0),
            proto=_proto(fields[29]),
            bytes=int(fields[31] or 0),
            packets=int(fields[32] or 0),
            action=fields[30],
            fqdn=None,
            app_id=fields[14] or None,
            source=PaloAltoAdapter.name,
            raw_id=None,
        )
    except (ValueError, IndexError):
        return None


def _parse_leef(line: str) -> FlowEvent | None:
    try:
        leef_start = line.index("LEEF:")
    except ValueError:
        return None
    tail = line[leef_start:]
    parts = tail.split("|")
    if len(parts) < _MIN_LEEF_PIPES:
        return None
    kvs: dict[str, str] = {}
    for segment in parts[5:]:
        for pair in segment.split("\t"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                kvs[k.strip()] = v.strip()
    # Some PAN LEEF emitters put k=v pairs on a single pipe-separated
    # extension; handle both cases defensively.
    for segment in parts:
        if "=" in segment:
            k, v = segment.split("=", 1)
            kvs.setdefault(k.strip(), v.strip())
    try:
        return FlowEvent(
            ts=datetime.now(UTC),
            src_ip=kvs["src"],
            src_port=int(kvs.get("srcPort", 0)),
            dst_ip=kvs["dst"],
            dst_port=int(kvs.get("dstPort", 0)),
            proto=_proto(kvs.get("proto", "tcp")),
            bytes=int(kvs.get("bytesTotal", 0)),
            packets=int(kvs.get("packetsTotal", 0)),
            action=kvs.get("action", "allow"),
            fqdn=kvs.get("hostname") or None,
            app_id=kvs.get("app") or None,
            source=PaloAltoAdapter.name,
            raw_id=None,
        )
    except (KeyError, ValueError):
        return None


def _ts(s: str) -> datetime:
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.now(UTC)
