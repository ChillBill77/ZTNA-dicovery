from __future__ import annotations

from typing import Any, Protocol


class _IdentityIndex(Protocol):
    def resolve(self, ip: str, at: Any) -> dict[str, Any] | None: ...


class _GroupIndex(Protocol):
    def groups_of(self, user: str) -> frozenset[str]: ...


class Enricher:
    """Per-row identity + group enrichment.

    Mutates ``row`` with ``user_upn`` (``"unknown"`` if no binding) and
    ``groups`` (a ``frozenset[str]``; empty for unknown). Runtime: O(1) lookup
    for a given ``(src_ip, ts)`` against the ``IdentityIndex`` tree.
    """

    def __init__(self, *, identity_index: _IdentityIndex, group_index: _GroupIndex) -> None:
        self._id = identity_index
        self._gi = group_index

    def enrich(self, row: dict[str, Any]) -> dict[str, Any]:
        hit = self._id.resolve(row["src_ip"], row["ts"])
        if hit is None:
            row["user_upn"] = "unknown"
            row["groups"] = frozenset()
            return row
        upn = hit["user_upn"]
        row["user_upn"] = upn
        row["groups"] = self._gi.groups_of(upn)
        return row
