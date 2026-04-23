from __future__ import annotations

from typing import Any

import pytest

from correlator.pipeline.group_index import GroupIndex


class FakeConn:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.listens: list[str] = []

    async def fetch(self, sql: str) -> list[dict[str, str]]:
        return list(self.rows)

    async def add_listener(self, channel: str, cb: Any) -> None:
        self.listens.append(channel)


@pytest.mark.asyncio
async def test_load_builds_user_to_groups_and_sizes() -> None:
    rows = [
        {"user_upn": "a", "group_id": "g1", "group_name": "G1"},
        {"user_upn": "a", "group_id": "g2", "group_name": "G2"},
        {"user_upn": "b", "group_id": "g1", "group_name": "G1"},
    ]
    idx = GroupIndex(FakeConn(rows))
    await idx.load()
    assert idx.groups_of("a") == frozenset({"g1", "g2"})
    assert idx.size_of("g1") == 2
    assert idx.size_of("g2") == 1
    assert idx.name_of("g1") == "G1"


@pytest.mark.asyncio
async def test_groups_of_unknown_user_is_empty_frozenset() -> None:
    idx = GroupIndex(FakeConn([]))
    await idx.load()
    assert idx.groups_of("nobody") == frozenset()


@pytest.mark.asyncio
async def test_listens_for_groups_changed_channel() -> None:
    conn = FakeConn([])
    idx = GroupIndex(conn)
    await idx.listen_for_changes()
    assert conn.listens == ["groups_changed"]
