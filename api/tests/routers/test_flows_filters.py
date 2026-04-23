"""Unit tests for the new identity-aware filters in ``/api/flows/sankey``.

Exercises the ``_filter_links`` helper directly with crafted deltas; full
live-mode + historical-mode coverage lives in the integration suite (P3
Chunk 7) which drives a real Redis + Postgres stack.
"""

from __future__ import annotations

from typing import Any

from api.routers.flows import _filter_links


def _delta(*labels: tuple[str, str]) -> dict[str, Any]:
    """Build a minimal delta with links labeled by (src, dst)."""

    links = [
        {"src": src, "dst": dst, "bytes": 100, "flows": 1, "users": 1}
        for src, dst in labels
    ]
    return {
        "ts": "2026-04-22T12:00:00Z",
        "window_s": 5,
        "nodes_left": [],
        "nodes_right": [],
        "links": links,
        "lossy": False,
        "dropped_count": 0,
    }


def _no_extra_filters() -> dict[str, Any]:
    return {
        "src_cidr": None,
        "dst_app": None,
        "category": None,
        "proto": None,
        "deny_only": False,
    }


def test_group_filter_narrows_to_selected_groups_and_unknown() -> None:
    delta = _delta(
        ("Sales EMEA", "app:m365"),
        ("Ops", "app:m365"),
        ("Marketing", "app:m365"),
        ("unknown", "app:m365"),
    )
    out = _filter_links(
        delta,
        **_no_extra_filters(),
        group_filter={"Sales EMEA", "Ops"},
    )
    srcs = {lk["src"] for lk in out["links"]}
    assert srcs == {"Sales EMEA", "Ops", "unknown"}


def test_user_filter_keeps_unknown_alongside_target_user() -> None:
    delta = _delta(
        ("alice@corp", "app:m365"),
        ("bob@corp", "app:m365"),
        ("unknown", "app:m365"),
    )
    out = _filter_links(
        delta,
        **_no_extra_filters(),
        user_filter="alice@corp",
    )
    srcs = {lk["src"] for lk in out["links"]}
    assert srcs == {"alice@corp", "unknown"}


def test_exclude_groups_drops_listed_labels() -> None:
    delta = _delta(
        ("Sales EMEA", "app:m365"),
        ("Everyone", "app:m365"),
        ("Domain Users", "app:m365"),
    )
    out = _filter_links(
        delta,
        **_no_extra_filters(),
        exclude_groups={"Everyone", "Domain Users"},
    )
    srcs = {lk["src"] for lk in out["links"]}
    assert srcs == {"Sales EMEA"}


def test_identity_filters_compose_with_src_cidr() -> None:
    delta = {
        "ts": "2026-04-22T12:00:00Z",
        "window_s": 5,
        "nodes_left": [],
        "nodes_right": [],
        "links": [
            {"src": "ip:10.0.12.34", "dst": "app:m365", "bytes": 1, "flows": 1, "users": 0},
            {"src": "ip:192.0.2.1", "dst": "app:m365", "bytes": 1, "flows": 1, "users": 0},
        ],
        "lossy": False,
        "dropped_count": 0,
    }
    out = _filter_links(
        delta,
        src_cidr="10.0.0.0/8",
        dst_app=None,
        category=None,
        proto=None,
        deny_only=False,
    )
    srcs = {lk["src"] for lk in out["links"]}
    assert srcs == {"ip:10.0.12.34"}
