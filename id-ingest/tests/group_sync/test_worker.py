from __future__ import annotations

import pytest

from id_ingest.group_sync.ad_sync import GroupUpsert
from id_ingest.group_sync.worker import GroupSyncWorker


class FakeSync:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.full_calls = 0

    async def sync_user(self, upn: str) -> list[GroupUpsert]:
        self.calls.append(upn)
        return [
            GroupUpsert(
                user_upn=upn,
                group_id="g",
                group_name="g",
                group_source="ad",
            )
        ]

    async def sync_all(self) -> list[GroupUpsert]:
        self.full_calls += 1
        return []


class FakeNotifier:
    def __init__(self) -> None:
        self.called = 0

    async def refresh_and_notify(self) -> None:
        self.called += 1


@pytest.mark.asyncio
async def test_worker_triggers_sync_on_unknown_upn() -> None:
    syncs = [FakeSync()]
    notifier = FakeNotifier()
    w = GroupSyncWorker(
        syncs=syncs,
        notifier=notifier,  # type: ignore[arg-type]
        full_sync_cron="0 2 * * *",
    )
    await w.on_new_upn("alice@example")
    assert syncs[0].calls == ["alice@example"]


@pytest.mark.asyncio
async def test_worker_skips_repeat_upn() -> None:
    syncs = [FakeSync()]
    w = GroupSyncWorker(
        syncs=syncs,
        notifier=None,
        full_sync_cron="0 2 * * *",
    )
    await w.on_new_upn("bob@example")
    await w.on_new_upn("bob@example")
    await w.on_new_upn("bob@example")
    assert syncs[0].calls == ["bob@example"]


@pytest.mark.asyncio
async def test_full_cycle_runs_every_sync_and_notifier() -> None:
    s1 = FakeSync()
    s2 = FakeSync()
    notifier = FakeNotifier()
    w = GroupSyncWorker(
        syncs=[s1, s2],
        notifier=notifier,  # type: ignore[arg-type]
        full_sync_cron="0 2 * * *",
    )
    await w._full_cycle()
    assert s1.full_calls == 1
    assert s2.full_calls == 1
    assert notifier.called == 1
