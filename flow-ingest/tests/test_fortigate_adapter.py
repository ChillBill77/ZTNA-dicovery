from __future__ import annotations

from pathlib import Path

from flow_ingest.adapters.fortigate_adapter import FortiGateAdapter

FIX = Path(__file__).parent / "fixtures" / "fortigate"


def test_parse_close_yields_event() -> None:
    line = (FIX / "traffic_close.kv").read_text().splitlines()[0]
    ev = FortiGateAdapter.parse_line(line)
    assert ev is not None
    assert ev["src_ip"] == "10.0.0.4"
    assert ev["dst_ip"] == "52.97.1.2"
    assert ev["dst_port"] == 443
    assert ev["proto"] == 6
    assert ev["bytes"] == 4096 + 2048
    assert ev["packets"] == 12 + 8
    assert ev["fqdn"] == "tenant.sharepoint.com"
    assert ev["app_id"] == "SharePoint"
    assert ev["source"] == "fortigate"


def test_non_close_is_dropped() -> None:
    line = (FIX / "traffic_non_close.kv").read_text().splitlines()[0]
    assert FortiGateAdapter.parse_line(line) is None
