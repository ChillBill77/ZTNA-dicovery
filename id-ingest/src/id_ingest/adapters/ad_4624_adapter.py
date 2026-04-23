from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import ClassVar

from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.event_types import IdentityEvent
from ztna_common.syslog_receiver import SyslogReceiver

# Spec §4.2 confidence table. Keys are stringified LogonType codes.
CONFIDENCE_BY_LOGON_TYPE: dict[str, int] = {"2": 90, "10": 90, "11": 50, "3": 70}
DEFAULT_TTL_S = 8 * 3600
ACCEPTED_LOGON_TYPES = {"2", "3", "10", "11"}


class Ad4624Adapter(IdentityAdapter):
    name: ClassVar[str] = "ad_4624"

    def __init__(self, host: str = "0.0.0.0", port: int = 516) -> None:
        self._recv = SyslogReceiver(host=host, port=port)

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> Ad4624Adapter:
        return cls(
            host=str(cfg.get("host", cfg.get("bind", "0.0.0.0"))),
            port=int(cfg.get("port", 516)),  # type: ignore[arg-type]
        )

    def parse(self, line: bytes) -> IdentityEvent | None:
        try:
            text = line.decode("utf-8", errors="replace")
            # Winlogbeat syslog frames JSON after the first ": " (process[pid]:)
            payload = text.split(": ", 1)[1] if ": " in text else text
            doc = json.loads(payload)
            if doc.get("event_id") != 4624:
                return None
            data = doc.get("winlog", {}).get("event_data", {})
            logon_type = str(data.get("LogonType", ""))
            ip = data.get("IpAddress")
            if logon_type not in ACCEPTED_LOGON_TYPES or not ip or ip == "-":
                return None
            upn = (
                f"{data['TargetUserName']}@{data.get('TargetDomainName', '')}".rstrip("@")
            )
            ts = datetime.fromisoformat(doc["@timestamp"].replace("Z", "+00:00"))
            return IdentityEvent(
                ts=ts,
                src_ip=ip,
                user_upn=upn,
                source=self.name,
                event_type="logon",
                confidence=CONFIDENCE_BY_LOGON_TYPE.get(logon_type, 50),
                ttl_seconds=DEFAULT_TTL_S,
                mac=None,
                raw_id=data.get("LogonGuid"),
            )
        except Exception as exc:  # noqa: BLE001 — adapters MUST NOT crash the service
            logger.warning("ad_4624 parse error: {}", exc)
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
