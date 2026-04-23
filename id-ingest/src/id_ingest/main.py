from __future__ import annotations

import asyncio
import importlib
import pkgutil
import signal
from collections.abc import Sequence

from loguru import logger
from ztna_common.adapter_base import IdentityAdapter

from id_ingest import adapters as adapters_pkg
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


async def _main() -> None:
    """Full runtime: start discovered adapters + group-sync worker + producer.

    Chunks 2-4 populate the real adapter + worker bodies; this shell exists so
    the Dockerfile ``CMD`` has a module to import and run.
    """

    settings = IdIngestSettings()
    logger.info("id-ingest starting (no adapters registered yet)")
    # Keep the process alive until signaled; real wiring lands in chunks 2-4.
    await run_once(timeout_s=float("inf"))
    _ = settings  # silence unused in the skeleton


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
