from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server

REGISTRY = CollectorRegistry(auto_describe=True)

IDENTITY_INGEST_EVENTS = Counter(
    "identity_ingest_events_total",
    "Identity events ingested, labelled by adapter.",
    ["adapter"],
    registry=REGISTRY,
)

IDENTITY_INGEST_PARSE_ERRORS = Counter(
    "identity_ingest_parse_errors_total",
    "Identity parse errors, labelled by adapter.",
    ["adapter"],
    registry=REGISTRY,
)

GROUP_SYNC_LAST_FULL_CYCLE_SECONDS = Gauge(
    "group_sync_last_full_cycle_seconds",
    "Wall-clock duration of the last completed full group-sync cycle.",
    registry=REGISTRY,
)


def start_metrics_server(port: int = 9100) -> None:
    """Bind the prometheus-client HTTP exporter to ``0.0.0.0:port``."""

    start_http_server(port, registry=REGISTRY)
