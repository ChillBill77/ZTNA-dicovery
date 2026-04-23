from __future__ import annotations

from pathlib import Path

import pytest

from flow_ingest.adapters.palo_alto_adapter import PaloAltoAdapter

FIX = Path(__file__).parent / "fixtures" / "palo_alto"


@pytest.mark.parametrize(
    "line,expected_src",
    [
        ((FIX / "traffic_end.csv").read_text().splitlines()[1], "10.0.0.1"),
    ],
)
def test_parse_csv_end_yields_event(line: str, expected_src: str) -> None:
    ev = PaloAltoAdapter.parse_line(line)
    assert ev is not None
    assert ev["src_ip"] == expected_src
    assert ev["dst_port"] == 443
    assert ev["proto"] == 6
    assert ev["bytes"] == 1024
    assert ev["action"] == "allow"
    assert ev["app_id"] == "ms-office365"
    assert ev["source"] == "palo_alto"


def test_parse_csv_start_is_dropped() -> None:
    line = (FIX / "traffic_start.csv").read_text().splitlines()[0]
    assert PaloAltoAdapter.parse_line(line) is None


def test_parse_leef() -> None:
    line = (FIX / "traffic_leef.txt").read_text().splitlines()[0]
    ev = PaloAltoAdapter.parse_line(line)
    assert ev is not None
    assert ev["src_ip"] == "10.0.0.3"
    assert ev["dst_ip"] == "142.250.190.46"
    assert ev["fqdn"] == "teams.microsoft.com"
    assert ev["app_id"] == "ms-teams"


def test_parse_garbage_returns_none() -> None:
    assert PaloAltoAdapter.parse_line("not-a-pan-line") is None
