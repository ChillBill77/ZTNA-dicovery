from __future__ import annotations

from flow_ingest.main import list_enabled_adapters
from flow_ingest.settings import AdapterConfig


def test_list_enabled_adapters() -> None:
    cfg = {
        "palo_alto": AdapterConfig(enabled=True, source_ips=frozenset({"10.0.0.1"})),
        "fortigate": AdapterConfig(enabled=False, source_ips=frozenset()),
    }
    names = list_enabled_adapters(cfg)
    assert names == ["palo_alto"]


def test_unknown_adapter_warned_not_crashed() -> None:
    cfg = {"mystery_source": AdapterConfig(enabled=True, source_ips=frozenset())}
    names = list_enabled_adapters(cfg)
    assert names == []
