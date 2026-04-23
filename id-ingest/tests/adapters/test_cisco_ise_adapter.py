from __future__ import annotations

from pathlib import Path

from id_ingest.adapters.cisco_ise_adapter import CiscoIseAdapter

FIX = Path(__file__).parent.parent / "fixtures" / "cisco_ise"


def _adapter() -> CiscoIseAdapter:
    return CiscoIseAdapter.from_config({})


def test_start_event_is_nac_auth_with_95_confidence() -> None:
    line = (FIX / "acct_start.txt").read_bytes().strip()
    ev = _adapter().parse(line)
    assert ev is not None
    assert ev["source"] == "cisco_ise"
    assert ev["event_type"] == "nac-auth"
    assert ev["user_upn"] == "alice"
    assert ev["src_ip"] == "10.0.12.34"
    assert ev["confidence"] == 95
    assert ev["ttl_seconds"] == 12 * 3600  # no Session-Timeout → 12h default
    assert ev["mac"] == "AA-BB-CC-DD-EE-FF"


def test_session_timeout_overrides_default_ttl() -> None:
    line = (FIX / "session_timeout.txt").read_bytes().strip()
    ev = _adapter().parse(line)
    assert ev is not None
    assert ev["ttl_seconds"] == 3600


def test_stop_event_marks_invalidation() -> None:
    line = (FIX / "acct_stop.txt").read_bytes().strip()
    ev = _adapter().parse(line)
    assert ev is not None
    assert ev["event_type"] == "nac-auth-stop"
    assert ev["ttl_seconds"] == 0
