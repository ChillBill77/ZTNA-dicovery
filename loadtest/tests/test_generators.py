from __future__ import annotations

from loadtest.generators.ad_4624_fixture import ad_4624_line
from loadtest.generators.fortigate_fixture import fortigate_traffic_line
from loadtest.generators.ise_fixture import ise_accounting_line
from loadtest.generators.pan_fixture import pan_traffic_line


def test_pan_line_is_csv_and_ends_newline() -> None:
    line = pan_traffic_line()
    assert line.endswith(b"\n")
    assert b"TRAFFIC,end" in line


def test_fortigate_is_kv_and_has_required_keys() -> None:
    line = fortigate_traffic_line()
    for key in (b"srcip=", b"dstip=", b"dstport=", b"sentbyte="):
        assert key in line


def test_ad_4624_has_eventid_and_ip() -> None:
    line = ad_4624_line()
    assert b"EventID=4624" in line
    assert b"IpAddress=" in line


def test_ise_has_accounting_and_ip() -> None:
    line = ise_accounting_line()
    assert b"CISE_RADIUS_Accounting" in line
    assert b"Framed-IP-Address=" in line
