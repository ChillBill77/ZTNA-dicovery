from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TypedDict


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


class FlowAdapter(ABC):
    """Base class for flow adapters. Subclasses set class attribute `name`
    and implement `run()` (async iterator of FlowEvents) and `healthcheck()`.
    """

    name: str = ""

    @abstractmethod
    async def run(self) -> AsyncIterator[FlowEvent]:  # pragma: no cover - abstract
        raise NotImplementedError
        yield

    @abstractmethod
    def healthcheck(self) -> dict[str, object]:  # pragma: no cover - abstract
        raise NotImplementedError
