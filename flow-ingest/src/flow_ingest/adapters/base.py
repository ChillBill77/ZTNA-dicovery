from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, TypedDict

if TYPE_CHECKING:
    from flow_ingest.publisher import RedisFlowPublisher
    from flow_ingest.syslog_receiver import SyslogReceiver


class FlowEvent(TypedDict):
    ts: datetime
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    action: str  # 'allow' | 'deny' | 'drop'
    fqdn: str | None  # firewall-supplied hostname
    app_id: str | None  # vendor App-ID
    source: str  # adapter name, e.g. 'palo_alto'
    raw_id: str | None


@dataclass
class FlowAdapter(ABC):
    """Base class for flow adapters. Subclasses set class attribute ``name``
    and implement ``run()`` (async iterator of FlowEvents) and ``healthcheck()``.

    Common wiring (syslog receiver, redis publisher, optional peer allowlist)
    lives on the base so callers can construct adapters polymorphically.
    """

    receiver: SyslogReceiver
    publisher: RedisFlowPublisher
    peer_allowlist: set[str] | None = field(default=None)

    name: ClassVar[str] = ""

    @abstractmethod
    async def run(self) -> AsyncIterator[FlowEvent]:  # pragma: no cover - abstract
        raise NotImplementedError
        yield

    @abstractmethod
    def healthcheck(self) -> dict[str, object]:  # pragma: no cover - abstract
        raise NotImplementedError
