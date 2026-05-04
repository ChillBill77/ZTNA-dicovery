"""LCD-aware ``SankeyPublisher`` integration tests.

These cover the wiring of ``GroupAggregator`` into the publisher: per-tick
emission, LCD hits/misses, unknown-user routing, and the metric counters.
We use a hand-rolled fake Redis with a ``.publish`` recorder rather than
``fakeredis`` so we can assert on the serialized JSON payload directly
without spinning up a pubsub subscriber.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from correlator.pipeline.app_resolver import AppCandidate
from correlator.pipeline.group_aggregator import GroupAggregator
from correlator.pipeline.metrics import (
    CORRELATOR_LCD_MISS,
    CORRELATOR_UNKNOWN_USER_RATIO,
)
from correlator.pipeline.sankey_publisher import LabelledFlow, SankeyPublisher


class FakeRedis:
    """Minimal stand-in for ``redis.asyncio.Redis`` (set/publish only)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.last_set: tuple[str, str] | None = None

    async def set(self, key: str, value: str) -> None:
        self.last_set = (key, value)

    async def publish(self, channel: str, value: str) -> None:
        self.published.append((channel, value))


class FakeGroupIndex:
    """Minimal ``GroupIndex`` stub exposing ``group_sizes`` + ``size_of``."""

    def __init__(self, sizes: dict[str, int]) -> None:
        self._sizes = sizes

    @property
    def group_sizes(self) -> dict[str, int]:
        return dict(self._sizes)

    def size_of(self, group_id: str) -> int:
        return self._sizes.get(group_id, 0)


def _flow(
    *,
    bucket: datetime,
    src_ip: str = "10.0.0.1",
    user_upn: str = "unknown",
    groups: frozenset[str] = frozenset(),
    label: str = "M365",
    label_kind: str = "saas",
    bytes_: int = 100,
    flow_count: int = 1,
    lossy: bool = False,
    dropped_count: int = 0,
) -> LabelledFlow:
    return LabelledFlow(
        bucket_start=bucket,
        window_s=5,
        src_ip=src_ip,
        dst_ip="52.97.1.1",
        dst_port=443,
        proto=6,
        bytes=bytes_,
        packets=1,
        flow_count=flow_count,
        candidate=AppCandidate(label_kind=label_kind, label=label, app_id=1),
        lossy=lossy,
        dropped_count=dropped_count,
        user_upn=user_upn,
        groups=groups,
    )


async def _drive_publisher(
    flows: list[LabelledFlow],
    *,
    aggregator: GroupAggregator | None,
    group_index: FakeGroupIndex | None,
    group_by: str = "group",
) -> tuple[FakeRedis, list[dict[str, Any]]]:
    """Feed ``flows`` through one publisher tick and return published deltas."""
    redis = FakeRedis()
    q: asyncio.Queue[LabelledFlow] = asyncio.Queue()
    pub = SankeyPublisher(
        inp=q,
        redis=redis,  # type: ignore[arg-type]
        aggregator=aggregator,
        group_index=group_index,  # type: ignore[arg-type]
        group_by=group_by,
    )
    for f in flows:
        await q.put(f)
    # Sentinel to advance the window and trigger a publish.
    if flows:
        sentinel = _flow(
            bucket=flows[-1].bucket_start + timedelta(seconds=flows[-1].window_s),
            src_ip="10.0.0.255",
            user_upn="unknown",
        )
        await q.put(sentinel)

    task = asyncio.create_task(pub.run())
    # Drain the queue. Using a tight wait_for loop keeps the test fast
    # without resorting to arbitrary sleeps.
    for _ in range(50):
        if redis.published:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    deltas = [json.loads(payload) for _ch, payload in redis.published]
    return redis, deltas


@pytest.mark.asyncio
async def test_empty_input_publishes_nothing() -> None:
    redis, deltas = await _drive_publisher(
        [],
        aggregator=GroupAggregator(excluded=set()),
        group_index=FakeGroupIndex({}),
    )
    assert deltas == []
    assert redis.last_set is None


@pytest.mark.asyncio
async def test_single_user_one_group_emits_single_lcd_link() -> None:
    bucket = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    agg = GroupAggregator(excluded=set(), single_user_floor=500)
    gi = FakeGroupIndex({"g:sales": 7})
    flows = [
        _flow(
            bucket=bucket,
            src_ip="10.0.0.1",
            user_upn="alice@example.com",
            groups=frozenset({"g:sales"}),
            bytes_=100,
            flow_count=2,
        )
    ]
    _redis, deltas = await _drive_publisher(flows, aggregator=agg, group_index=gi)
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta["window_s"] == 5
    links = delta["links"]
    sales = [l for l in links if l["src"] == "g:sales"]
    assert len(sales) == 1
    assert sales[0]["dst"] == "app:M365"
    assert sales[0]["users"] == 1
    assert sales[0]["bytes"] == 100
    # left-side node carries group size from the index.
    sales_node = next(n for n in delta["nodes_left"] if n["id"] == "g:sales")
    assert sales_node["size"] == 7
    # right-side node carries the candidate kind.
    m365 = next(n for n in delta["nodes_right"] if n["id"] == "app:M365")
    assert m365["kind"] == "saas"


@pytest.mark.asyncio
async def test_two_users_sharing_group_collapse_to_one_lcd_link_users_two() -> None:
    bucket = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    agg = GroupAggregator(excluded={"Everyone"}, single_user_floor=500)
    gi = FakeGroupIndex({"g:sales": 50, "Everyone": 9999})
    flows = [
        _flow(
            bucket=bucket,
            src_ip="10.0.0.1",
            user_upn="alice@example.com",
            groups=frozenset({"g:sales", "Everyone"}),
            bytes_=100,
        ),
        _flow(
            bucket=bucket,
            src_ip="10.0.0.2",
            user_upn="bob@example.com",
            groups=frozenset({"g:sales", "Everyone"}),
            bytes_=200,
            flow_count=2,
        ),
    ]
    _redis, deltas = await _drive_publisher(flows, aggregator=agg, group_index=gi)
    assert len(deltas) == 1
    links = deltas[0]["links"]
    sales = [l for l in links if l["src"] == "g:sales" and l["dst"] == "app:M365"]
    assert len(sales) == 1
    assert sales[0]["users"] == 2
    assert sales[0]["bytes"] == 300
    assert sales[0]["flows"] == 3


@pytest.mark.asyncio
async def test_lcd_miss_falls_back_to_per_user_strands_and_increments_metric() -> None:
    bucket = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    # Both users share only the excluded "Everyone" group → LCD miss.
    agg = GroupAggregator(excluded={"Everyone"}, single_user_floor=500)
    gi = FakeGroupIndex({"Everyone": 9999})
    flows = [
        _flow(
            bucket=bucket,
            src_ip="10.0.0.1",
            user_upn="alice@example.com",
            groups=frozenset({"Everyone"}),
            bytes_=10,
        ),
        _flow(
            bucket=bucket,
            src_ip="10.0.0.2",
            user_upn="bob@example.com",
            groups=frozenset({"Everyone"}),
            bytes_=20,
        ),
    ]
    before_miss = CORRELATOR_LCD_MISS._value.get()  # type: ignore[attr-defined]
    _redis, deltas = await _drive_publisher(flows, aggregator=agg, group_index=gi)
    assert len(deltas) == 1
    srcs = {l["src"] for l in deltas[0]["links"]}
    assert srcs == {"alice@example.com", "bob@example.com"}
    after_miss = CORRELATOR_LCD_MISS._value.get()  # type: ignore[attr-defined]
    assert after_miss - before_miss >= 2


@pytest.mark.asyncio
async def test_unknown_users_routed_to_unknown_strand_and_ratio_set() -> None:
    bucket = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    agg = GroupAggregator(excluded=set(), single_user_floor=500)
    gi = FakeGroupIndex({"g:sales": 7})
    flows = [
        _flow(
            bucket=bucket,
            src_ip="10.0.0.1",
            user_upn="alice@example.com",
            groups=frozenset({"g:sales"}),
            bytes_=100,
        ),
        _flow(
            bucket=bucket,
            src_ip="10.0.0.99",
            user_upn="unknown",
            groups=frozenset(),
            bytes_=50,
        ),
    ]
    _redis, deltas = await _drive_publisher(flows, aggregator=agg, group_index=gi)
    assert len(deltas) == 1
    srcs = {l["src"] for l in deltas[0]["links"]}
    assert "unknown" in srcs
    assert "g:sales" in srcs
    # 1 out of 2 enriched flows had user_upn='unknown' → ratio 0.5.
    ratio = CORRELATOR_UNKNOWN_USER_RATIO._value.get()  # type: ignore[attr-defined]
    assert ratio == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_aggregator_none_preserves_legacy_p2_shape() -> None:
    bucket = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    flows = [
        _flow(
            bucket=bucket,
            src_ip="10.0.0.1",
            user_upn="alice@example.com",
            groups=frozenset({"g:sales"}),
            bytes_=100,
        ),
    ]
    _redis, deltas = await _drive_publisher(
        flows, aggregator=None, group_index=None, group_by="group"
    )
    assert len(deltas) == 1
    # Legacy mode emits ``ip:<src>`` → ``app:<label>`` links.
    links = deltas[0]["links"]
    assert any(l["src"] == "ip:10.0.0.1" and l["dst"] == "app:M365" for l in links)


@pytest.mark.asyncio
async def test_lossy_or_reduced_and_dropped_count_summed_across_window() -> None:
    bucket = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    agg = GroupAggregator(excluded=set(), single_user_floor=500)
    gi = FakeGroupIndex({"g:sales": 5})
    flows = [
        _flow(
            bucket=bucket,
            user_upn="alice@example.com",
            groups=frozenset({"g:sales"}),
            lossy=False,
            dropped_count=2,
        ),
        _flow(
            bucket=bucket,
            user_upn="alice@example.com",
            groups=frozenset({"g:sales"}),
            lossy=True,
            dropped_count=3,
        ),
    ]
    _redis, deltas = await _drive_publisher(flows, aggregator=agg, group_index=gi)
    assert deltas[0]["lossy"] is True
    assert deltas[0]["dropped_count"] == 5
