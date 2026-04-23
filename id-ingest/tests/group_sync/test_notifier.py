from __future__ import annotations

import pytest

from id_ingest.group_sync.notifier import GroupChangeNotifier


class FakeConn:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, stmt: str) -> None:
        self.sql.append(stmt)


@pytest.mark.asyncio
async def test_refresh_and_notify_emits_both_statements() -> None:
    conn = FakeConn()
    notifier = GroupChangeNotifier(conn)
    await notifier.refresh_and_notify()
    assert any("REFRESH MATERIALIZED VIEW CONCURRENTLY group_members" in s for s in conn.sql)
    assert any("NOTIFY groups_changed" in s for s in conn.sql)


@pytest.mark.asyncio
async def test_statement_order_refresh_before_notify() -> None:
    conn = FakeConn()
    await GroupChangeNotifier(conn).refresh_and_notify()
    # REFRESH must precede NOTIFY so subscribers see a fresh view.
    refresh_idx = next(i for i, s in enumerate(conn.sql) if "REFRESH" in s)
    notify_idx = next(i for i, s in enumerate(conn.sql) if "NOTIFY" in s)
    assert refresh_idx < notify_idx
