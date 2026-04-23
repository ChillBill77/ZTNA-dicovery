from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from correlator.pipeline.identity_index import IdentityIndex

FIX = Path(__file__).parent.parent / "fixtures" / "identity"


def _load(name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (FIX / name).read_text().splitlines()
        if line.strip()
    ]


def test_resolve_picks_highest_confidence_within_ttl() -> None:
    idx = IdentityIndex()
    events = _load("events_mixed_confidence.jsonl")
    for ev in events:
        idx.insert(ev)
    ip = events[0]["src_ip"]
    t = datetime.fromisoformat(events[0]["ts"].replace("Z", "+00:00"))
    resolved = idx.resolve(ip, t + timedelta(seconds=10))
    assert resolved is not None
    assert resolved["confidence"] == max(e["confidence"] for e in events)


def test_resolve_tiebreaks_by_most_recent() -> None:
    idx = IdentityIndex()
    ip = "10.0.0.1"
    idx.insert(
        {
            "ts": "2026-04-22T12:00:00+00:00",
            "src_ip": ip,
            "user_upn": "older",
            "source": "x",
            "event_type": "logon",
            "confidence": 90,
            "ttl_seconds": 3600,
        }
    )
    idx.insert(
        {
            "ts": "2026-04-22T12:10:00+00:00",
            "src_ip": ip,
            "user_upn": "newer",
            "source": "x",
            "event_type": "logon",
            "confidence": 90,
            "ttl_seconds": 3600,
        }
    )
    out = idx.resolve(ip, datetime(2026, 4, 22, 12, 20, tzinfo=UTC))
    assert out is not None
    assert out["user_upn"] == "newer"


def test_stop_event_invalidates_prior_binding() -> None:
    idx = IdentityIndex()
    ip = "10.0.0.2"
    idx.insert(
        {
            "ts": "2026-04-22T12:00:00+00:00",
            "src_ip": ip,
            "user_upn": "bob",
            "source": "ise",
            "event_type": "nac-auth",
            "confidence": 95,
            "ttl_seconds": 3600,
        }
    )
    idx.insert(
        {
            "ts": "2026-04-22T12:05:00+00:00",
            "src_ip": ip,
            "user_upn": "bob",
            "source": "ise",
            "event_type": "nac-auth-stop",
            "confidence": 95,
            "ttl_seconds": 0,
        }
    )
    assert idx.resolve(ip, datetime(2026, 4, 22, 12, 10, tzinfo=UTC)) is None


def test_expired_ttl_evicted() -> None:
    idx = IdentityIndex()
    events = _load("events_expired_ttl.jsonl")
    for ev in events:
        idx.insert(ev)
    ip = events[0]["src_ip"]
    probe = datetime.fromisoformat(events[0]["ts"].replace("Z", "+00:00")) + timedelta(
        seconds=120
    )
    assert idx.resolve(ip, probe) is None
    assert idx.size() == 0


def test_size_metric_reports_active_intervals() -> None:
    idx = IdentityIndex()
    for ev in _load("events_basic.jsonl"):
        idx.insert(ev)
    assert idx.size() == 2
