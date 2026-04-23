from __future__ import annotations

from datetime import UTC, datetime

from ztna_common.event_types import FlowEvent, IdentityEvent


def test_flow_event_typed_dict_round_trip() -> None:
    ev: FlowEvent = {
        "ts": datetime.now(UTC),
        "src_ip": "10.0.0.1",
        "src_port": 44321,
        "dst_ip": "52.97.1.1",
        "dst_port": 443,
        "proto": 6,
        "bytes": 1024,
        "packets": 8,
        "action": "allow",
        "fqdn": None,
        "app_id": None,
        "source": "palo_alto",
        "raw_id": None,
    }
    assert ev["source"] == "palo_alto"


def test_identity_event_typed_dict_round_trip() -> None:
    ev: IdentityEvent = {
        "ts": datetime.now(UTC),
        "src_ip": "10.0.12.34",
        "user_upn": "alice@corp",
        "source": "ad_4624",
        "event_type": "logon",
        "confidence": 90,
        "ttl_seconds": 28800,
        "mac": None,
        "raw_id": None,
    }
    assert ev["confidence"] == 90
