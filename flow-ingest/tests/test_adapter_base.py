from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest
from flow_ingest.adapters.base import FlowAdapter, FlowEvent


def test_flow_event_shape() -> None:
    sample: FlowEvent = {
        "ts": datetime.now(UTC),
        "src_ip": "10.0.0.1",
        "src_port": 44321,
        "dst_ip": "52.97.1.1",
        "dst_port": 443,
        "proto": 6,
        "bytes": 1024,
        "packets": 8,
        "action": "allow",
        "fqdn": "outlook.office365.com",
        "app_id": "ms-office365",
        "source": "palo_alto",
        "raw_id": "abc123",
    }
    assert sample["source"] == "palo_alto"


def test_flow_adapter_is_abstract() -> None:
    assert inspect.isabstract(FlowAdapter)
    with pytest.raises(TypeError):
        FlowAdapter()  # type: ignore[abstract]


def test_subclass_must_implement_run_and_health() -> None:
    class Partial(FlowAdapter):
        name = "partial"

    with pytest.raises(TypeError):
        Partial()  # type: ignore[abstract]
