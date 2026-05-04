from __future__ import annotations

import asyncio
import contextlib
import json
import signal
from datetime import datetime
from typing import Any

import asyncpg
import uvloop
from loguru import logger
from redis.asyncio import Redis

from correlator.pipeline.app_resolver import (
    AppResolver,
    ManualApp,
    PortDefault,
    SaasEntry,
)
from correlator.pipeline.enricher import Enricher
from correlator.pipeline.group_aggregator import GroupAggregator
from correlator.pipeline.group_index import GroupIndex
from correlator.pipeline.identity_index import IdentityIndex
from correlator.pipeline.metrics import IDENTITY_INDEX_SIZE
from correlator.pipeline.sankey_publisher import LabelledFlow, SankeyPublisher
from correlator.pipeline.windower import FlowWindower, WindowedFlow
from correlator.pipeline.writer import Writer
from correlator.settings import CorrelatorSettings

# P3 identity pipeline wiring landed in Cycle 2 follow-up: `_identity_consumer`
# reads from the `identity.events` Redis stream into the in-memory
# IdentityIndex; GroupIndex is loaded from `user_groups` at startup and
# refreshed on Postgres `NOTIFY groups_changed`; `_label_stage` now invokes
# the `Enricher` before pushing to the downstream queue so `LabelledFlow`
# carries `user_upn` + `groups`. The LCD `GroupAggregator` is still consumed
# off-path — wiring it into the Sankey publish step is the next follow-up.


async def _read_xstream_into(
    redis: Redis,
    stream: str,
    out: asyncio.Queue[dict[str, Any]],
    group: str = "correlator",
) -> None:
    # Ensure group exists
    with contextlib.suppress(Exception):  # group already exists
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    consumer = "c1"
    while True:
        entries = await redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=500,
            block=1000,
        )
        for _s, msgs in entries:
            for msg_id, fields in msgs:
                try:
                    ev = json.loads(fields["event"])
                    # ts back to datetime
                    ev["ts"] = datetime.fromisoformat(ev["ts"])
                except Exception:
                    await redis.xack(stream, group, msg_id)
                    continue
                await out.put(ev)
                await redis.xack(stream, group, msg_id)


async def _label_stage(
    inp: asyncio.Queue[WindowedFlow],
    out: asyncio.Queue[LabelledFlow],
    resolver: AppResolver,
    enricher: Enricher | None = None,
) -> None:
    while True:
        wf: WindowedFlow = await inp.get()
        cand = await resolver.resolve(
            dst_ip=wf.dst_ip,
            dst_port=wf.dst_port,
            proto=wf.proto,
            firewall_fqdn=wf.fqdn,
            app_id=wf.app_id,
        )
        lf = LabelledFlow(
            bucket_start=wf.bucket_start,
            window_s=wf.window_s,
            src_ip=wf.src_ip,
            dst_ip=wf.dst_ip,
            dst_port=wf.dst_port,
            proto=wf.proto,
            bytes=wf.bytes,
            packets=wf.packets,
            flow_count=wf.flow_count,
            candidate=cand,
            lossy=wf.lossy,
            dropped_count=wf.dropped_count,
        )
        if enricher is not None:
            # Mutates ``row`` (the dict view) with user_upn + groups; copy back
            # onto the LabelledFlow's identity fields so downstream stages see
            # the enrichment without reaching into a dict.
            row: dict[str, Any] = {"src_ip": lf.src_ip, "ts": lf.bucket_start}
            enricher.enrich(row)
            lf.user_upn = row.get("user_upn", "unknown")
            groups = row.get("groups", frozenset())
            lf.groups = groups if isinstance(groups, frozenset) else frozenset(groups)
        await out.put(lf)


async def _identity_consumer(
    redis: Redis,
    stream: str,
    id_idx: IdentityIndex,
    group: str = "correlator",
) -> None:
    """Consume ``identity.events`` into the in-memory IdentityIndex.

    Mirrors ``_read_xstream_into`` but drives IdentityIndex.insert() directly.
    XADD-ed events with an ISO-format ``ts`` are coerced to ``datetime``.
    Updates the ``identity_index_size`` gauge once per batch so the Grafana
    dashboard can chart it without re-reading internal state.
    """

    with contextlib.suppress(Exception):
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    consumer = "c1"
    while True:
        entries = await redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=500,
            block=1000,
        )
        for _s, msgs in entries:
            for msg_id, fields in msgs:
                try:
                    ev = json.loads(fields["event"])
                    if isinstance(ev.get("ts"), str):
                        ev["ts"] = datetime.fromisoformat(ev["ts"])
                    id_idx.insert(ev)
                except Exception as exc:
                    logger.warning("identity event parse error: {}", exc)
                await redis.xack(stream, group, msg_id)
        IDENTITY_INDEX_SIZE.set(id_idx.size())


async def _load_app_resolver(resolver: AppResolver, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        manual_rows = await conn.fetch(
            """SELECT id, name, dst_cidr::text AS cidr, dst_port_min AS port_min,
                      dst_port_max AS port_max, proto, priority
               FROM applications"""
        )
        saas_rows = await conn.fetch(
            "SELECT id, name, fqdn_pattern AS pattern, priority FROM saas_catalog"
        )
        port_rows = await conn.fetch("SELECT port, proto, name FROM port_defaults")
    resolver.load(
        manual=[ManualApp(**dict(r)) for r in manual_rows],
        saas=[SaasEntry(**dict(r)) for r in saas_rows],
        port_defaults=[PortDefault(**dict(r)) for r in port_rows],
    )


async def _listen_reload(pool: asyncpg.Pool, resolver: AppResolver, dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    # Hold references to spawned reload tasks so they aren't GC'd mid-flight.
    _reload_tasks: set[asyncio.Task[None]] = set()

    def _cb(*_args: object) -> None:
        t = asyncio.create_task(_load_app_resolver(resolver, pool))
        _reload_tasks.add(t)
        t.add_done_callback(_reload_tasks.discard)

    try:
        await conn.add_listener("applications_changed", _cb)
        await conn.add_listener("saas_changed", _cb)
        while True:
            await asyncio.sleep(3600)
    finally:
        await conn.close()


def _as_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


async def _demux(src: asyncio.Queue[LabelledFlow], *dsts: asyncio.Queue[LabelledFlow]) -> None:
    while True:
        item = await src.get()
        for d in dsts:
            try:
                d.put_nowait(item)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    _ = d.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    d.put_nowait(item)


async def _run(settings: CorrelatorSettings) -> None:
    from ztna_common.logging_config import configure as configure_logging

    from correlator.pipeline.metrics import start_metrics_server

    configure_logging(settings.log_level)
    start_metrics_server(settings.metrics_port)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    dsn = _as_asyncpg_dsn(settings.database_url)
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=8)

    resolver = AppResolver(redis=redis)
    await _load_app_resolver(resolver, pool)

    # Identity pipeline (P3 wiring). Dedicated long-lived connection for
    # GroupIndex so its `LISTEN groups_changed` subscription isn't recycled
    # by the shared pool; identity consumer populates the in-memory index.
    id_idx = IdentityIndex()
    groups_conn = await asyncpg.connect(dsn)
    grp_idx = GroupIndex(groups_conn)
    await grp_idx.load()
    await grp_idx.listen_for_changes()
    enricher = Enricher(identity_index=id_idx, group_index=grp_idx)
    aggregator = GroupAggregator(
        excluded=set(settings.excluded_groups),
        single_user_floor=settings.single_user_floor,
    )

    async def _drop_agg_cache(*_args: Any) -> None:
        aggregator.clear_cache()

    await groups_conn.add_listener("groups_changed", _drop_agg_cache)

    raw_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=settings.queue_max)
    windowed_q: asyncio.Queue[WindowedFlow] = asyncio.Queue(maxsize=settings.queue_max)
    labelled_q_writer: asyncio.Queue[LabelledFlow] = asyncio.Queue(maxsize=settings.queue_max)
    labelled_q_sankey: asyncio.Queue[LabelledFlow] = asyncio.Queue(maxsize=settings.queue_max)
    intermediate_q: asyncio.Queue[LabelledFlow] = asyncio.Queue(maxsize=settings.queue_max)

    windower = FlowWindower(inp=raw_q, out=windowed_q, window_s=settings.window_s)
    writer = Writer(
        inp=labelled_q_writer, pool=pool, batch_size=settings.batch_size, flush_ms=settings.flush_ms
    )
    sankey_pub = SankeyPublisher(
        inp=labelled_q_sankey,
        redis=redis,
        aggregator=aggregator,
        group_index=grp_idx,
        group_by="group",
    )

    tasks = [
        asyncio.create_task(_read_xstream_into(redis, settings.flows_stream, raw_q), name="xread"),
        asyncio.create_task(
            _identity_consumer(redis, settings.identity_stream, id_idx),
            name="identity-consumer",
        ),
        asyncio.create_task(windower.run(), name="windower"),
        asyncio.create_task(
            _label_stage(windowed_q, intermediate_q, resolver, enricher),
            name="labeller",
        ),
        asyncio.create_task(
            _demux(intermediate_q, labelled_q_writer, labelled_q_sankey), name="demux"
        ),
        asyncio.create_task(writer.run(), name="writer"),
        asyncio.create_task(sankey_pub.run(), name="sankey-pub"),
        asyncio.create_task(_listen_reload(pool, resolver, dsn), name="reload"),
    ]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    logger.info("correlator shutting down")
    for t in tasks:
        t.cancel()
    with contextlib.suppress(Exception):
        await groups_conn.close()
    await pool.close()
    await redis.close()


def main() -> None:
    uvloop.install()
    asyncio.run(_run(CorrelatorSettings()))


if __name__ == "__main__":
    main()
