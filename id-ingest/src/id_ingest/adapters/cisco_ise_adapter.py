from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar

from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.event_types import IdentityEvent
from ztna_common.syslog_receiver import SyslogReceiver

_KV = re.compile(r"(?P<k>[A-Za-z][A-Za-z0-9-]*)\s*=\s*(?P<v>[^,]+)")
DEFAULT_TTL = 12 * 3600


class CiscoIseAdapter(IdentityAdapter):
    name: ClassVar[str] = "cisco_ise"

    def __init__(self, host: str = "0.0.0.0", port: int = 517) -> None:
        self._recv = SyslogReceiver(host=host, port=port)

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> CiscoIseAdapter:
        return cls(
            host=str(cfg.get("host", cfg.get("bind", "0.0.0.0"))),
            port=int(cfg.get("port", 517)),  # type: ignore[arg-type]
        )

    def parse(self, line: bytes) -> IdentityEvent | None:
        try:
            text = line.decode("utf-8", errors="replace")
            if "CISE_RADIUS_Accounting" not in text:
                return None
            kv = {m["k"]: m["v"].strip() for m in _KV.finditer(text)}
            status = kv.get("Acct-Status-Type", "")
            ip = kv.get("Framed-IP-Address")
            user = kv.get("UserName")
            if not ip or not user or status not in {"Start", "Stop"}:
                return None
            ts = datetime.now(tz=UTC)
            ttl = 0 if status == "Stop" else int(kv.get("Session-Timeout", str(DEFAULT_TTL)))
            return IdentityEvent(
                ts=ts,
                src_ip=ip,
                user_upn=user,
                source=self.name,
                event_type="nac-auth-stop" if status == "Stop" else "nac-auth",
                confidence=95,
                ttl_seconds=ttl,
                mac=kv.get("Calling-Station-ID"),
                raw_id=kv.get("Acct-Session-Id"),
            )
        except Exception as exc:
            logger.warning("cisco_ise parse error: {}", exc)
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
