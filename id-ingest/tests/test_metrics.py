from __future__ import annotations

from id_ingest.metrics import (
    GROUP_SYNC_LAST_FULL_CYCLE_SECONDS,
    IDENTITY_INGEST_EVENTS,
    REGISTRY,
)
from prometheus_client import generate_latest


def test_events_counter_is_exposed() -> None:
    IDENTITY_INGEST_EVENTS.labels(adapter="ad_4624").inc()
    body = generate_latest(REGISTRY).decode()
    assert 'identity_ingest_events_total{adapter="ad_4624"}' in body


def test_group_sync_gauge_is_exposed() -> None:
    GROUP_SYNC_LAST_FULL_CYCLE_SECONDS.set(42.0)
    body = generate_latest(REGISTRY).decode()
    assert "group_sync_last_full_cycle_seconds" in body
    assert "42.0" in body
