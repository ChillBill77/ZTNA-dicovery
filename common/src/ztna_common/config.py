from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AdapterConfig:
    """Generic adapter YAML config loaded from ``/etc/flowvis/adapters/<name>.yaml``.

    ``enabled`` gates adapter startup; ``source_ips`` is an optional allowlist of
    peer IPs (push-based syslog adapters only forward events whose sender IP is
    listed). Extra per-adapter keys live in ``options`` as a raw dict.
    """

    enabled: bool = True
    source_ips: frozenset[str] = field(default_factory=frozenset)
    options: dict[str, Any] = field(default_factory=dict)


def load_adapter_configs(path: Path) -> dict[str, AdapterConfig]:
    """Read every ``*.yaml`` under ``path`` and return ``{stem: AdapterConfig}``.

    Missing directories or unreadable files return an empty dict rather than
    raising so adapters degrade to their in-code defaults.
    """

    out: dict[str, AdapterConfig] = {}
    if not path.is_dir():
        return out
    for yml in sorted(path.glob("*.yaml")):
        data: dict[str, Any] = yaml.safe_load(yml.read_text()) or {}
        known = {"enabled", "source_ips"}
        out[yml.stem] = AdapterConfig(
            enabled=bool(data.get("enabled", True)),
            source_ips=frozenset(data.get("source_ips", []) or []),
            options={k: v for k, v in data.items() if k not in known},
        )
    return out
