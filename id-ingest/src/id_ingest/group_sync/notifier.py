from __future__ import annotations

from typing import Protocol


class _AsyncSql(Protocol):
    async def execute(self, stmt: str) -> None: ...


class GroupChangeNotifier:
    """Refreshes ``group_members`` MV and fires ``NOTIFY groups_changed``.

    Parameterized on an async SQL connection that exposes ``.execute(str)``,
    so both ``asyncpg.Connection`` and test doubles satisfy the contract.
    """

    def __init__(self, conn: _AsyncSql) -> None:
        self._conn = conn

    async def refresh_and_notify(self) -> None:
        await self._conn.execute(
            "REFRESH MATERIALIZED VIEW CONCURRENTLY group_members;"
        )
        await self._conn.execute("NOTIFY groups_changed;")
