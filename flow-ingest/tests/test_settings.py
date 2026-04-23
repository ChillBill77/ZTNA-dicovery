from __future__ import annotations

from pathlib import Path

from flow_ingest.settings import AdapterConfig, load_adapter_configs


def test_load_adapter_configs(tmp_path: Path) -> None:
    (tmp_path / "palo_alto.yaml").write_text("enabled: true\nsource_ips: [10.0.0.1]\n")
    (tmp_path / "fortigate.yaml").write_text("enabled: false\nsource_ips: []\n")
    configs = load_adapter_configs(tmp_path)
    assert configs["palo_alto"] == AdapterConfig(enabled=True, source_ips=frozenset({"10.0.0.1"}))
    assert configs["fortigate"] == AdapterConfig(enabled=False, source_ips=frozenset())
