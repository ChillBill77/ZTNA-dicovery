from __future__ import annotations

from flow_ingest.metrics import (
    FLOW_INGEST_EVENTS,
    FLOW_INGEST_PARSE_ERRORS,
    REGISTRY,
)
from prometheus_client import generate_latest


def test_events_counter_is_exposed() -> None:
    FLOW_INGEST_EVENTS.labels(adapter="palo_alto", source="firewall").inc()
    body = generate_latest(REGISTRY).decode()
    assert 'flow_ingest_events_total{adapter="palo_alto",source="firewall"}' in body


def test_parse_errors_counter_is_exposed() -> None:
    FLOW_INGEST_PARSE_ERRORS.labels(adapter="fortigate").inc()
    body = generate_latest(REGISTRY).decode()
    assert 'flow_ingest_parse_errors_total{adapter="fortigate"}' in body
