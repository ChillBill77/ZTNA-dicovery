from __future__ import annotations

from prometheus_client import generate_latest

from correlator.pipeline.metrics import (
    CORRELATOR_DROPPED_FLOWS,
    CORRELATOR_LCD_MISS,
    CORRELATOR_QUEUE_DEPTH,
    CORRELATOR_UNKNOWN_USER_RATIO,
    IDENTITY_INDEX_SIZE,
    POSTGRES_FLUSH_DURATION_SECONDS,
    POSTGRES_INSERT_BATCH_SECONDS,
    REGISTRY,
)


def test_queue_depth_gauge_is_exposed() -> None:
    CORRELATOR_QUEUE_DEPTH.labels(stage="windower").set(42)
    body = generate_latest(REGISTRY).decode()
    assert 'correlator_queue_depth{stage="windower"}' in body
    assert "42" in body


def test_dropped_flows_counter_is_exposed() -> None:
    CORRELATOR_DROPPED_FLOWS.inc()
    body = generate_latest(REGISTRY).decode()
    assert "correlator_dropped_flows_total" in body


def test_lcd_miss_counter_is_exposed() -> None:
    CORRELATOR_LCD_MISS.inc()
    body = generate_latest(REGISTRY).decode()
    assert "correlator_lcd_miss_total" in body


def test_unknown_user_ratio_gauge_is_exposed() -> None:
    CORRELATOR_UNKNOWN_USER_RATIO.set(0.23)
    body = generate_latest(REGISTRY).decode()
    assert "correlator_unknown_user_ratio" in body


def test_identity_index_size_gauge_is_exposed() -> None:
    IDENTITY_INDEX_SIZE.set(1000)
    body = generate_latest(REGISTRY).decode()
    assert "identity_index_size" in body


def test_postgres_histograms_exposed() -> None:
    POSTGRES_INSERT_BATCH_SECONDS.observe(0.05)
    POSTGRES_FLUSH_DURATION_SECONDS.observe(0.01)
    body = generate_latest(REGISTRY).decode()
    assert "postgres_insert_batch_size_seconds_bucket" in body
    assert "postgres_flush_duration_seconds_bucket" in body
