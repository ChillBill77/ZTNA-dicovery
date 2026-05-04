from __future__ import annotations

from pathlib import Path

import pytest
from id_ingest.adapters.ad_4624_adapter import Ad4624Adapter

FIX = Path(__file__).parent.parent / "fixtures" / "ad_4624"


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (
            "type2_interactive.txt",
            {
                "user_upn": "alice@CORP",
                "src_ip": "10.0.12.34",
                "confidence": 90,
                "ttl_seconds": 28800,
            },
        ),
        (
            "type3_network.txt",
            {
                "user_upn": "svc_backup@CORP",
                "src_ip": "10.0.5.17",
                "confidence": 70,
                "ttl_seconds": 28800,
            },
        ),
        (
            "type10_remote.txt",
            {
                "user_upn": "alice@CORP",
                "src_ip": "203.0.113.7",
                "confidence": 90,
                "ttl_seconds": 28800,
            },
        ),
    ],
)
def test_parse_single_line(fixture: str, expected: dict[str, object]) -> None:
    adapter = Ad4624Adapter.from_config({})
    line = (FIX / fixture).read_bytes().strip()
    ev = adapter.parse(line)
    assert ev is not None
    for k, v in expected.items():
        assert ev[k] == v  # type: ignore[literal-required]
    assert ev["event_type"] == "logon"
    assert ev["source"] == "ad_4624"


def test_parse_skips_missing_ip() -> None:
    adapter = Ad4624Adapter.from_config({})
    line = (FIX / "type11_cached.txt").read_bytes().strip()
    assert adapter.parse(line) is None


def test_parse_malformed_returns_none_without_raising() -> None:
    adapter = Ad4624Adapter.from_config({})
    line = (FIX / "malformed.txt").read_bytes().strip()
    assert adapter.parse(line) is None
