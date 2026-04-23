from __future__ import annotations

from pathlib import Path

from ztna_common.config import AdapterConfig, load_adapter_configs


def test_load_reads_enabled_flag_and_source_ips(tmp_path: Path) -> None:
    (tmp_path / "palo_alto.yaml").write_text(
        "enabled: true\nsource_ips:\n  - 10.0.0.1\n  - 10.0.0.2\n"
    )
    (tmp_path / "fortigate.yaml").write_text("enabled: false\n")
    out = load_adapter_configs(tmp_path)
    assert out["palo_alto"].enabled is True
    assert out["palo_alto"].source_ips == frozenset({"10.0.0.1", "10.0.0.2"})
    assert out["fortigate"].enabled is False


def test_load_missing_dir_returns_empty() -> None:
    out = load_adapter_configs(Path("/nonexistent-path-for-test"))
    assert out == {}


def test_adapter_config_defaults() -> None:
    cfg = AdapterConfig()
    assert cfg.enabled is True
    assert cfg.source_ips == frozenset()
    assert cfg.options == {}


def test_extra_keys_land_in_options(tmp_path: Path) -> None:
    (tmp_path / "cisco_ise.yaml").write_text(
        "enabled: true\nsource_ips: [10.0.100.10]\nbind: 0.0.0.0\nport: 517\n"
    )
    out = load_adapter_configs(tmp_path)
    cfg = out["cisco_ise"]
    assert cfg.options == {"bind": "0.0.0.0", "port": 517}
