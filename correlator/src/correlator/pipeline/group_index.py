from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class _AsyncConn(Protocol):
    async def fetch(self, sql: str) -> Any: ...

    async def add_listener(self, channel: str, cb: Callable[..., Awaitable[None]]) -> Any: ...


class GroupIndex:
    """In-memory ``user_upn → frozenset[group_id]`` + ``group_id → size`` view.

    Loaded from ``user_groups`` and refreshed on Postgres ``NOTIFY groups_changed``.
    """

    def __init__(self, conn: _AsyncConn) -> None:
        self._conn = conn
        self._user_groups: dict[str, frozenset[str]] = {}
        self._group_size: dict[str, int] = {}
        self._group_name: dict[str, str] = {}

    async def load(self) -> None:
        rows = await self._conn.fetch("SELECT user_upn, group_id, group_name FROM user_groups")
        ug: dict[str, set[str]] = defaultdict(set)
        names: dict[str, str] = {}
        for r in rows:
            ug[r["user_upn"]].add(r["group_id"])
            names[r["group_id"]] = r["group_name"]
        self._user_groups = {u: frozenset(gs) for u, gs in ug.items()}
        self._group_name = names
        sizes: dict[str, int] = defaultdict(int)
        for gs in self._user_groups.values():
            for g in gs:
                sizes[g] += 1
        self._group_size = dict(sizes)

    async def listen_for_changes(self) -> None:
        async def _reload(*_: Any) -> None:
            await self.load()

        await self._conn.add_listener("groups_changed", _reload)

    def groups_of(self, user: str) -> frozenset[str]:
        return self._user_groups.get(user, frozenset())

    def size_of(self, group_id: str) -> int:
        return self._group_size.get(group_id, 0)

    def name_of(self, group_id: str) -> str:
        return self._group_name.get(group_id, group_id)

    @property
    def group_sizes(self) -> dict[str, int]:
        return dict(self._group_size)
