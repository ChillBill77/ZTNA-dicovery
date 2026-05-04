from __future__ import annotations

import asyncio
import importlib
import pkgutil
import signal
from collections.abc import Sequence

from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.logging_config import configure as configure_logging

from id_ingest import adapters as adapters_pkg
from id_ingest.metrics import start_metrics_server
from id_ingest.redis_io import make_producer
from id_ingest.settings import IdIngestSettings


def discover_adapters() -> Sequence[type[IdentityAdapter]]:
    """Scan ``id_ingest.adapters`` for concrete IdentityAdapter subclasses.

    Adapter modules are named ``*_adapter.py`` and expose a class that inherits
    from :class:`ztna_common.adapter_base.IdentityAdapter`. Returns the classes
    (not instances) so callers can pick their own construction strategy.
    """

    found: list[type[IdentityAdapter]] = []
    for modinfo in pkgutil.iter_modules(adapters_pkg.__path__):
        if not modinfo.name.endswith("_adapter"):
            continue
        mod = importlib.import_module(f"id_ingest.adapters.{modinfo.name}")
        for obj in vars(mod).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, IdentityAdapter)
                and obj is not IdentityAdapter
            ):
                found.append(obj)
    return found


async def run_once(timeout_s: float = 1.0) -> bool:
    """Bring-up smoke helper — install signal handlers, wait up to ``timeout_s``,
    and return True on clean shutdown. Used by tests to exercise the shutdown
    path without wiring any adapters.
    """

    settings = IdIngestSettings()
    producer = make_producer(settings.redis_url)
    stop_evt = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, stop_evt.set)
        loop.add_signal_handler(signal.SIGINT, stop_evt.set)
    except (NotImplementedError, RuntimeError):
        # Signal handlers not supported in this loop (e.g., on Windows or
        # inside a nested event loop from pytest-asyncio).
        pass
    try:
        await asyncio.wait_for(stop_evt.wait(), timeout=timeout_s)
    except TimeoutError:
        pass
    finally:
        await producer.aclose()
    return True


def _build_adapter(
    cls: type[IdentityAdapter], settings: IdIngestSettings
) -> IdentityAdapter | None:
    """Construct one adapter with settings-derived config.

    Returns ``None`` when a required env var is absent for that adapter (e.g.,
    Entra without a tenant). The caller drops ``None`` entries so the remaining
    adapters still run.
    """

    name = cls.name
    from_config = getattr(cls, "from_config", None)
    if from_config is None:
        return None
    if name == "ad_4624":
        return from_config({"port": settings.ad_syslog_port})  # type: ignore[no-any-return]
    if name == "cisco_ise":
        return from_config({"port": settings.ise_syslog_port})  # type: ignore[no-any-return]
    if name == "aruba_clearpass":
        return from_config({"port": settings.clearpass_syslog_port})  # type: ignore[no-any-return]
    if name == "entra_signin":
        if not settings.entra_tenant_id:
            logger.info("entra_signin skipped: ENTRA_TENANT_ID not set")
            return None
        corp_cidrs = [c.strip() for c in settings.entra_corp_cidrs.split(",") if c.strip()]
        return from_config(  # type: ignore[no-any-return]
            {
                "tenant_id": settings.entra_tenant_id,
                "client_id": settings.entra_client_id,
                "client_secret": settings.entra_client_secret,
                "corp_cidrs": corp_cidrs,
                "poll_interval_s": settings.entra_poll_interval_s,
            }
        )
    logger.warning("unknown adapter {}; skipping", name)
    return None


async def _main() -> None:
    """Full runtime: start discovered adapters + group-sync worker + producer."""

    settings = IdIngestSettings()
    configure_logging(settings.log_level)
    start_metrics_server(settings.metrics_port)
    producer = make_producer(settings.redis_url)

    # Instantiate adapters via auto-discovery + settings-driven config.
    discovered = list(discover_adapters())
    instances: list[IdentityAdapter] = []
    for cls in discovered:
        try:
            a = _build_adapter(cls, settings)
        except Exception as exc:
            logger.warning("adapter {} build failed: {}", cls.name, exc)
            continue
        if a is not None:
            instances.append(a)
    logger.info(
        "id-ingest: {} adapter(s) registered: {}",
        len(instances),
        [a.name for a in instances],
    )

    # Group-sync worker (optional: only active if AD or Entra credentials set).
    from id_ingest.group_sync.ad_sync import AdGroupSync
    from id_ingest.group_sync.entra_sync import EntraGroupSync
    from id_ingest.group_sync.notifier import GroupChangeNotifier
    from id_ingest.group_sync.worker import GroupSyncWorker

    syncs: list[object] = []
    if settings.ad_ldap_url:
        syncs.append(
            AdGroupSync(
                ldap_url=settings.ad_ldap_url,
                bind_dn=settings.ad_bind_dn,
                bind_password=settings.ad_bind_password,
                base_dn=settings.ad_base_dn,
            )
        )
    if settings.entra_tenant_id:
        syncs.append(
            EntraGroupSync(
                tenant_id=settings.entra_tenant_id,
                client_id=settings.entra_client_id,
                client_secret=settings.entra_client_secret,
            )
        )

    notifier: GroupChangeNotifier | None = None
    if settings.database_url:
        try:
            import asyncpg

            pg = await asyncpg.connect(settings.database_url)
            notifier = GroupChangeNotifier(pg)
        except Exception as exc:
            logger.warning("notifier init failed; refresh+NOTIFY disabled: {}", exc)

    worker = GroupSyncWorker(
        syncs=syncs,  # type: ignore[arg-type]
        notifier=notifier,
        full_sync_cron=settings.group_sync_full_cron,
    )
    if syncs:
        worker.start()

    async def _run_adapter(a: IdentityAdapter) -> None:
        async for ev in a.run():
            await producer.xadd(ev)
            upn = ev.get("user_upn")
            if upn and syncs:
                await worker.on_new_upn(upn)

    try:
        if instances:
            await asyncio.gather(*[_run_adapter(a) for a in instances])
        else:
            logger.info("no adapters registered; idling")
            await run_once(timeout_s=float("inf"))
    finally:
        await worker.aclose()
        await producer.aclose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
