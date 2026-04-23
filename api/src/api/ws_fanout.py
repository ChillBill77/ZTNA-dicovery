from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from redis.asyncio import Redis


@dataclass
class ClientState:
    send: Callable[[str], Awaitable[None]]
    filters: dict[str, Any] = field(default_factory=dict)  # src_cidr, dst_app, proto, deny_only

    def matches(self, link: dict[str, Any]) -> bool:
        src_cidr = self.filters.get("src_cidr")
        if src_cidr:
            try:
                ip = ipaddress.ip_address(link["src"].removeprefix("ip:"))
                if ip not in ipaddress.ip_network(src_cidr, strict=False):
                    return False
            except ValueError:
                return False
        dst_app = self.filters.get("dst_app")
        return not (dst_app and link["dst"] != f"app:{dst_app}")


class SankeyFanout:
    def __init__(self, redis: Redis, channel: str = "sankey.live") -> None:
        self.redis = redis
        self.channel = channel
        self._clients: list[ClientState] = []
        self._task: asyncio.Task[None] | None = None

    def add_client(self, c: ClientState) -> None:
        self._clients.append(c)

    def remove_client(self, c: ClientState) -> None:
        self._clients = [x for x in self._clients if x is not c]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sankey-fanout")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        async with self.redis.pubsub() as sub:
            await sub.subscribe(self.channel)
            while True:
                msg = await sub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                if msg is None:
                    continue
                try:
                    payload = json.loads(msg["data"])
                except Exception:
                    continue
                await self._dispatch(payload)

    async def _dispatch(self, delta: dict[str, Any]) -> None:
        for c in list(self._clients):
            filtered = {**delta, "links": [lk for lk in delta["links"] if c.matches(lk)]}
            try:
                await c.send(json.dumps(filtered))
            except Exception as exc:
                logger.debug("ws send failed, dropping client: {}", exc)
                self.remove_client(c)
