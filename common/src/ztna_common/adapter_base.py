from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from ztna_common.event_types import FlowEvent, IdentityEvent

if TYPE_CHECKING:
    from ztna_common.redis_bus import RedisFlowPublisher
    from ztna_common.syslog_receiver import SyslogReceiver


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


class IdentityAdapter(ABC):
    """Async identity adapter; emits IdentityEvent per session binding.

    Identity adapters are not dataclasses because they can take arbitrary
    constructor arguments (LDAP/Graph credentials, CIDR lists, mock transports
    for tests) that don't fit the flow-adapter dataclass shape.
    """

    name: ClassVar[str] = ""

    @abstractmethod
    async def run(self) -> AsyncIterator[IdentityEvent]:  # pragma: no cover - abstract
        raise NotImplementedError
        yield

    @abstractmethod
    def healthcheck(self) -> dict[str, object]:  # pragma: no cover - abstract
        raise NotImplementedError
