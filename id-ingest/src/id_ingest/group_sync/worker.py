from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from id_ingest.group_sync.ad_sync import GroupUpsert
from id_ingest.group_sync.notifier import GroupChangeNotifier


class _Sync(Protocol):
    async def sync_user(self, upn: str) -> list[GroupUpsert]: ...

    async def sync_all(self) -> Any: ...


class GroupSyncWorker:
    """Drives periodic full syncs + on-demand per-UPN syncs.

    - ``on_new_upn(upn)`` is idempotent per process: the first sighting of a
      UPN triggers a per-adapter ``sync_user`` call; subsequent sightings are
      no-ops until the process restarts.
    - A cron-scheduled ``_full_cycle`` runs all adapters' ``sync_all``, then
      fires the notifier (if configured) so subscribers refresh their caches.
    """

    def __init__(
        self,
        *,
        syncs: Sequence[_Sync],
        notifier: GroupChangeNotifier | None,
        full_sync_cron: str,
        metrics_hook: Callable[[str, float], None] | None = None,
    ) -> None:
        self._syncs = list(syncs)
        self._notifier = notifier
        self._cron = full_sync_cron
        self._seen_upns: set[str] = set()
        self._sched = AsyncIOScheduler()
        self._metrics = metrics_hook

    async def on_new_upn(self, upn: str) -> None:
        if upn in self._seen_upns:
            return
        self._seen_upns.add(upn)
        for s in self._syncs:
            await s.sync_user(upn)

    async def _full_cycle(self) -> None:
        started = asyncio.get_event_loop().time()
        for s in self._syncs:
            result = s.sync_all()
            if hasattr(result, "__aiter__"):
                async for _ in result:
                    pass
            else:
                await result
        if self._notifier is not None:
            await self._notifier.refresh_and_notify()
        elapsed = asyncio.get_event_loop().time() - started
        if self._metrics is not None:
            self._metrics("group_sync_last_full_cycle_seconds", elapsed)

    def start(self) -> None:
        self._sched.add_job(
            self._full_cycle, CronTrigger.from_crontab(self._cron)
        )
        self._sched.start()

    async def aclose(self) -> None:
        self._sched.shutdown(wait=False)
