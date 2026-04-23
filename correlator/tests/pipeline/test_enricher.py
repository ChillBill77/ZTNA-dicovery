from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from correlator.pipeline.enricher import Enricher


class FakeIdx:
    def resolve(self, ip: str, at: Any) -> dict[str, Any] | None:
        if ip == "10.0.0.1":
            return {"user_upn": "alice", "confidence": 90}
        return None


class FakeGroups:
    def groups_of(self, upn: str) -> frozenset[str]:
        if upn == "alice":
            return frozenset({"g:sales"})
        return frozenset()


def test_enricher_attaches_upn_and_groups() -> None:
    e = Enricher(identity_index=FakeIdx(), group_index=FakeGroups())
    row: dict[str, Any] = {
        "ts": datetime(2026, 4, 22, 12, tzinfo=UTC),
        "src_ip": "10.0.0.1",
        "dst_ip": "1.1.1.1",
        "dst_port": 443,
        "bytes": 100,
    }
    out = e.enrich(row)
    assert out["user_upn"] == "alice"
    assert out["groups"] == frozenset({"g:sales"})


def test_enricher_marks_unknown_when_no_binding() -> None:
    e = Enricher(identity_index=FakeIdx(), group_index=FakeGroups())
    row: dict[str, Any] = {
        "ts": datetime.now(UTC),
        "src_ip": "10.0.9.9",
        "dst_ip": "1.1.1.1",
        "dst_port": 443,
    }
    out = e.enrich(row)
    assert out["user_upn"] == "unknown"
    assert out["groups"] == frozenset()
