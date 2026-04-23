from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import uvloop
from loguru import logger
from redis.asyncio import Redis
from ztna_common.adapter_base import FlowAdapter
from ztna_common.redis_bus import RedisFlowPublisher
from ztna_common.syslog_receiver import SyslogReceiver

from flow_ingest.adapters.fortigate_adapter import FortiGateAdapter
from flow_ingest.adapters.palo_alto_adapter import PaloAltoAdapter
from flow_ingest.settings import AdapterConfig, IngestSettings, load_adapter_configs

_ADAPTER_REGISTRY: dict[str, type[FlowAdapter]] = {
    PaloAltoAdapter.name: PaloAltoAdapter,
    FortiGateAdapter.name: FortiGateAdapter,
}


def list_enabled_adapters(configs: dict[str, AdapterConfig]) -> list[str]:
    out: list[str] = []
    for name, cfg in configs.items():
        if not cfg.enabled:
            continue
        if name not in _ADAPTER_REGISTRY:
            logger.warning("unknown adapter {}; skipping", name)
            continue
        out.append(name)
    return out


async def _drain_adapter(adapter: FlowAdapter) -> None:
    async for _ in adapter.run():  # adapter publishes; we just keep draining
        pass


async def _run(settings: IngestSettings) -> None:
    configs = load_adapter_configs(Path(settings.config_dir))
    logger.info("loaded configs: {}", {k: v.enabled for k, v in configs.items()})

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    publisher = RedisFlowPublisher(redis=redis)
    receiver = SyslogReceiver(
        host=settings.syslog_host,
        port=settings.syslog_port,
        queue_max=settings.queue_max,
    )
    await receiver.start()

    tasks: list[asyncio.Task[None]] = []
    for name in list_enabled_adapters(configs):
        cls = _ADAPTER_REGISTRY[name]
        adapter = cls(
            receiver=receiver,
            publisher=publisher,
            peer_allowlist=set(configs[name].source_ips) or None,
        )
        tasks.append(asyncio.create_task(_drain_adapter(adapter), name=f"adapter:{name}"))

    stop = asyncio.Event()

    def _signal() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal)

    await stop.wait()
    logger.info("shutdown signal received; stopping")
    for t in tasks:
        t.cancel()
    await publisher.flush()
    await receiver.stop()
    await redis.close()


def main() -> None:
    uvloop.install()
    asyncio.run(_run(IngestSettings()))


if __name__ == "__main__":
    main()
