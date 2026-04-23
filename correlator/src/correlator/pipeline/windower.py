from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger


@dataclass(frozen=True)
class _Key:
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int


@dataclass
class _Acc:
    bytes: int = 0
    packets: int = 0
    flow_count: int = 0
    app_id_seen: str | None = None
    fqdn_seen: str | None = None
    action_seen: str | None = None


@dataclass
class WindowedFlow:
    bucket_start: datetime
    window_s: int
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    flow_count: int
    app_id: str | None
    fqdn: str | None
    action: str | None
    lossy: bool = False
    dropped_count: int = 0


@dataclass
class FlowWindower:
    inp: asyncio.Queue
    out: asyncio.Queue
    window_s: int = 5
    tick_s: float = 1.0
    _buckets: dict[datetime, dict[_Key, _Acc]] = field(init=False, default_factory=dict)
    _dropped: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self._buckets = {}
        self._dropped = 0

    def _bucket_start(self, ts: datetime) -> datetime:
        epoch = int(ts.timestamp())
        aligned = epoch - (epoch % self.window_s)
        tzinfo = ts.tzinfo or timezone.utc
        return datetime.fromtimestamp(aligned, tz=tzinfo)

    async def _emit_ready(self, now: datetime) -> None:
        threshold = self._bucket_start(now) - timedelta(seconds=self.window_s)
        ready = [b for b in self._buckets if b <= threshold]
        for b in sorted(ready):
            for key, acc in self._buckets.pop(b).items():
                wf = WindowedFlow(
                    bucket_start=b, window_s=self.window_s,
                    src_ip=key.src_ip, dst_ip=key.dst_ip,
                    dst_port=key.dst_port, proto=key.proto,
                    bytes=acc.bytes, packets=acc.packets, flow_count=acc.flow_count,
                    app_id=acc.app_id_seen, fqdn=acc.fqdn_seen, action=acc.action_seen,
                    lossy=self._dropped > 0, dropped_count=self._dropped,
                )
                try:
                    self.out.put_nowait(wf)
                except asyncio.QueueFull:
                    try:
                        _ = self.out.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._dropped += 1
                    try:
                        self.out.put_nowait(wf)
                    except asyncio.QueueFull:
                        logger.warning("windower out queue still full; dropping")
        if ready:
            self._dropped = 0  # reset once flushed; next window starts clean

    async def run(self) -> None:
        while True:
            try:
                ev = await asyncio.wait_for(self.inp.get(), timeout=self.tick_s)
            except asyncio.TimeoutError:
                await self._emit_ready(datetime.now(tz=timezone.utc))
                continue
            ts: datetime = ev["ts"]
            bucket = self._bucket_start(ts)
            key = _Key(ev["src_ip"], ev["dst_ip"], int(ev["dst_port"]), int(ev["proto"]))
            slot = self._buckets.setdefault(bucket, {})
            acc = slot.setdefault(key, _Acc())
            acc.bytes += int(ev["bytes"])
            acc.packets += int(ev["packets"])
            acc.flow_count += 1
            # carry through first-seen values; later reconciled by AppResolver
            acc.app_id_seen = acc.app_id_seen or ev.get("app_id")
            acc.fqdn_seen = acc.fqdn_seen or ev.get("fqdn")
            acc.action_seen = acc.action_seen or ev.get("action")
            await self._emit_ready(ts)
