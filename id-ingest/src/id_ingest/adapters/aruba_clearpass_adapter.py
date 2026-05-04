from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar

from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.event_types import IdentityEvent
from ztna_common.syslog_receiver import SyslogReceiver

DEFAULT_TTL = 12 * 3600
_CEF_FIELDS = re.compile(r"(?P<k>[a-zA-Z0-9]+)=(?P<v>[^\s]+)")
_HEADER = re.compile(
    r"CEF:0\|[^|]+\|ClearPass\|[^|]+\|(?P<sig>\d+)\|(?P<name>[^|]+)\|\d+\|(?P<ext>.*)"
)


class ArubaClearpassAdapter(IdentityAdapter):
    name: ClassVar[str] = "aruba_clearpass"

    def __init__(self, host: str = "0.0.0.0", port: int = 518) -> None:
        self._recv = SyslogReceiver(host=host, port=port)

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> ArubaClearpassAdapter:
        return cls(
            host=str(cfg.get("host", cfg.get("bind", "0.0.0.0"))),
            port=int(cfg.get("port", 518)),  # type: ignore[arg-type]
        )

    def parse(self, line: bytes) -> IdentityEvent | None:
        try:
            text = line.decode("utf-8", errors="replace")
            m = _HEADER.search(text)
            if not m:
                return None
            name = m.group("name")
            kv = {f["k"]: f["v"] for f in _CEF_FIELDS.finditer(m.group("ext"))}
            # ClearPass labels session-timeout via paired cs2Label/cs2 fields.
            ttl = DEFAULT_TTL
            if kv.get("cs2Label") == "Session-Timeout" and "cs2" in kv:
                ttl = int(kv["cs2"])
            is_stop = "Stop" in name
            ts = datetime.now(tz=UTC)
            return IdentityEvent(
                ts=ts,
                src_ip=kv["src"],
                user_upn=kv["suser"],
                source=self.name,
                event_type="nac-auth-stop" if is_stop else "nac-auth",
                confidence=95,
                ttl_seconds=0 if is_stop else ttl,
                mac=kv.get("smac"),
                raw_id=kv.get("externalId"),
            )
        except Exception as exc:
            logger.warning("aruba_clearpass parse error: {}", exc)
            return None

    async def run(self) -> AsyncIterator[IdentityEvent]:
        await self._recv.start()
        try:
            while True:
                _peer, line = await self._recv.queue.get()
                ev = self.parse(line.encode("utf-8"))
                if ev is not None:
                    yield ev
        finally:
            await self._recv.stop()

    def healthcheck(self) -> dict[str, object]:
        return {
            "adapter": self.name,
            "listening": self._recv.udp_port != 0 or self._recv.tcp_port != 0,
        }
