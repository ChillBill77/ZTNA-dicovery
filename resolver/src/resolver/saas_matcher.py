from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SaasRow:
    id: int
    name: str
    pattern: str  # suffix, typically starts with '.'
    priority: int = 100


class SaasMatcher:
    """Suffix matcher with priority + length tiebreak."""

    def __init__(self, rows: list[SaasRow]) -> None:
        # Sort rows once so `match` can short-circuit on the first hit.
        self._rows = sorted(rows, key=lambda r: (-r.priority, -len(r.pattern), r.id))

    def match(self, fqdn: str) -> SaasRow | None:
        lower = fqdn.lower()
        for row in self._rows:
            if lower.endswith(row.pattern.lower()):
                return row
        return None
