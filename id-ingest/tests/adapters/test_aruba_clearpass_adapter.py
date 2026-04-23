from __future__ import annotations

from pathlib import Path

from id_ingest.adapters.aruba_clearpass_adapter import ArubaClearpassAdapter

FIX = Path(__file__).parent.parent / "fixtures" / "clearpass"


def test_start_event_emits_nac_auth_at_95() -> None:
    adapter = ArubaClearpassAdapter.from_config({})
    line = (FIX / "cef_start.txt").read_bytes().strip()
    ev = adapter.parse(line)
    assert ev is not None
    assert ev["source"] == "aruba_clearpass"
    assert ev["event_type"] == "nac-auth"
    assert ev["user_upn"] == "bob@corp.example"
    assert ev["src_ip"] == "10.0.20.12"
    assert ev["confidence"] == 95
    assert ev["ttl_seconds"] == 7200
    assert ev["mac"] == "11:22:33:44:55:66"
    assert ev["raw_id"] == "CP-SESSION-987"


def test_stop_event_is_invalidating() -> None:
    adapter = ArubaClearpassAdapter.from_config({})
    line = (FIX / "cef_stop.txt").read_bytes().strip()
    ev = adapter.parse(line)
    assert ev is not None
    assert ev["event_type"] == "nac-auth-stop"
    assert ev["ttl_seconds"] == 0
