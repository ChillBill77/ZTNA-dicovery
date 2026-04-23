from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, cast

import asyncpg
from loguru import logger
from redis.asyncio import Redis


@dataclass(frozen=True)
class ManualApp:
    id: int
    name: str
    cidr: str
    port_min: int | None
    port_max: int | None
    proto: int | None
    priority: int = 100


@dataclass(frozen=True)
class SaasEntry:
    id: int
    name: str
    pattern: str
    priority: int = 100


@dataclass(frozen=True)
class PortDefault:
    port: int
    proto: int
    name: str


LabelKind = Literal["manual", "saas", "ptr", "port", "raw"]


@dataclass
class AppCandidate:
    label_kind: LabelKind
    label: str
    app_id: int | None = None


class AppResolver:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._manual: list[ManualApp] = []
        self._saas_sorted: list[SaasEntry] = []
        self._port_defaults: dict[tuple[int, int], PortDefault] = {}

    def load(
        self,
        manual: list[ManualApp],
        saas: list[SaasEntry],
        port_defaults: list[PortDefault],
    ) -> None:
        # Sort manual: highest priority, then most-specific CIDR (longest prefix).
        self._manual = sorted(
            manual,
            key=lambda a: (-a.priority, -ipaddress.ip_network(a.cidr).prefixlen),
        )
        self._saas_sorted = sorted(saas, key=lambda s: (-s.priority, -len(s.pattern), s.id))
        self._port_defaults = {(p.port, p.proto): p for p in port_defaults}
        logger.info(
            "app-resolver loaded manual={} saas={} ports={}",
            len(self._manual),
            len(self._saas_sorted),
            len(self._port_defaults),
        )

    def _manual_hit(self, ip: str, port: int, proto: int) -> ManualApp | None:
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for app in self._manual:
            if ip_obj not in ipaddress.ip_network(app.cidr):
                continue
            if app.proto is not None and app.proto != proto:
                continue
            if app.port_min is not None and port < app.port_min:
                continue
            if app.port_max is not None and port > app.port_max:
                continue
            return app
        return None

    def _saas_hit(self, fqdn: str) -> SaasEntry | None:
        lower = fqdn.lower()
        for s in self._saas_sorted:
            if lower.endswith(s.pattern.lower()):
                return s
        return None

    async def resolve(
        self,
        *,
        dst_ip: str,
        dst_port: int,
        proto: int,
        firewall_fqdn: str | None,
        app_id: str | None,
    ) -> AppCandidate:
        manual = self._manual_hit(dst_ip, dst_port, proto)
        if manual is not None:
            return AppCandidate(label_kind="manual", label=manual.name, app_id=manual.id)

        if firewall_fqdn:
            s = self._saas_hit(firewall_fqdn)
            if s is not None:
                return AppCandidate(label_kind="saas", label=s.name, app_id=s.id)

        ptr = await self.redis.get(f"dns:ptr:{dst_ip}")
        if ptr is None:
            # Unseen IP — schedule for the resolver worker.
            # redis-py types rpush as Union[Awaitable[int], int] because the
            # sync and async clients share a signature; on the async client it
            # always returns an Awaitable.
            await cast(Awaitable[int], self.redis.rpush("dns:unresolved", dst_ip))
        elif ptr:
            saas_id_str = await self.redis.get(f"dns:saas:{dst_ip}")
            if saas_id_str is not None:
                try:
                    saas_id = int(saas_id_str)
                except ValueError:
                    saas_id = -1
                match = next((s for s in self._saas_sorted if s.id == saas_id), None)
                if match is not None:
                    return AppCandidate(label_kind="ptr", label=match.name, app_id=match.id)

        port_hit = self._port_defaults.get((dst_port, proto))
        if port_hit is not None:
            return AppCandidate(label_kind="port", label=port_hit.name)

        return AppCandidate(label_kind="raw", label=f"{dst_ip}:{dst_port}")


async def listen_for_reload(
    resolver: AppResolver,
    dsn: str,
    reload_fn: Callable[[], None],
) -> None:
    """Background task: LISTEN on Postgres for config changes and call reload_fn()
    to rebuild resolver state. Registered from `main.py`. Implementer uses asyncpg
    `connection.add_listener` for `applications_changed` + `saas_changed`.

    The callback triggers `reload_fn` which queries Postgres, constructs the
    cache rows, and calls `resolver.load(...)`. The full callback body is wired
    in main.py where the asyncpg pool + queries live; this helper exists so
    tests can monkey-patch it out.
    """
    del resolver  # resolver is used only by reload_fn's closure
    conn = await asyncpg.connect(dsn)

    def _cb(*_args: object) -> None:
        reload_fn()

    try:
        await conn.add_listener("applications_changed", _cb)
        await conn.add_listener("saas_changed", _cb)
        while True:
            await asyncio.sleep(3600)  # heartbeat; listener fires independently.
    finally:
        await conn.close()
