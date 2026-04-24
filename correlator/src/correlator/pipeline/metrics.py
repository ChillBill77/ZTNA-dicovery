"""Prometheus metrics registry for the correlator.

Upgrades the P2 placeholder to real ``prometheus_client`` counters / gauges /
histograms. Spec §10 enumerates the metric names; add new ones here and wire
the increments from the call sites that own them (pipeline stages, writer).
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

REGISTRY = CollectorRegistry(auto_describe=True)

CORRELATOR_QUEUE_DEPTH = Gauge(
    "correlator_queue_depth",
    "Bounded queue depth per pipeline stage.",
    ["stage"],
    registry=REGISTRY,
)

CORRELATOR_DROPPED_FLOWS = Counter(
    "correlator_dropped_flows_total",
    "Flows dropped due to queue overflow.",
    registry=REGISTRY,
)

CORRELATOR_UNKNOWN_USER_RATIO = Gauge(
    "correlator_unknown_user_ratio",
    "Ratio of enriched flows in the last window with user_upn='unknown'.",
    registry=REGISTRY,
)

CORRELATOR_LCD_MISS = Counter(
    "correlator_lcd_miss_total",
    "LCD lookups that returned no group and fell back to per-user strands.",
    registry=REGISTRY,
)

IDENTITY_INDEX_SIZE = Gauge(
    "identity_index_size",
    "Current in-memory IdentityIndex size (sum of interval trees across src_ips).",
    registry=REGISTRY,
)

POSTGRES_INSERT_BATCH_SECONDS = Histogram(
    "postgres_insert_batch_size_seconds",
    "Postgres batch insert duration, seconds.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    registry=REGISTRY,
)

POSTGRES_FLUSH_DURATION_SECONDS = Histogram(
    "postgres_flush_duration_seconds",
    "Postgres explicit flush duration, seconds.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    registry=REGISTRY,
)


def start_metrics_server(port: int = 9100) -> None:
    """Bind the prometheus-client HTTP exporter to ``0.0.0.0:port``."""

    start_http_server(port, registry=REGISTRY)
