from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, start_http_server

REGISTRY = CollectorRegistry(auto_describe=True)

FLOW_INGEST_EVENTS = Counter(
    "flow_ingest_events_total",
    "Flow events ingested, labelled by adapter and normalized source.",
    ["adapter", "source"],
    registry=REGISTRY,
)

FLOW_INGEST_PARSE_ERRORS = Counter(
    "flow_ingest_parse_errors_total",
    "Flow parse errors, labelled by adapter.",
    ["adapter"],
    registry=REGISTRY,
)


def start_metrics_server(port: int = 9100) -> None:
    """Bind the prometheus-client HTTP exporter to ``0.0.0.0:port``.

    Called once at service startup; safe to skip in unit tests.
    """

    start_http_server(port, registry=REGISTRY)
