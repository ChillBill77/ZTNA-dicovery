from __future__ import annotations

from typing import Any

from correlator.pipeline.group_aggregator import GroupAggregator, lcd


def test_lcd_picks_smallest_common_non_excluded_group() -> None:
    user_groups: dict[str, frozenset[str] | set[str]] = {
        "a": {"Sales", "Sales EMEA", "Everyone"},
        "b": {"Sales", "Sales EMEA", "Everyone"},
    }
    sizes = {"Sales": 300, "Sales EMEA": 50, "Everyone": 10000}
    chosen = lcd({"a", "b"}, user_groups, sizes, excluded={"Everyone"}, floor=500)
    assert chosen == "Sales EMEA"


def test_lcd_returns_none_when_only_excluded_groups_match() -> None:
    user_groups: dict[str, frozenset[str] | set[str]] = {
        "a": {"Everyone"},
        "b": {"Everyone"},
    }
    sizes = {"Everyone": 10000}
    assert lcd({"a", "b"}, user_groups, sizes, excluded={"Everyone"}) is None


def test_lcd_returns_none_for_disjoint_groups() -> None:
    user_groups: dict[str, frozenset[str] | set[str]] = {
        "a": {"Red"},
        "b": {"Blue"},
    }
    sizes = {"Red": 5, "Blue": 5}
    assert lcd({"a", "b"}, user_groups, sizes, excluded=set()) is None


def test_lcd_single_user_over_floor_falls_back_to_user_strand() -> None:
    user_groups: dict[str, frozenset[str] | set[str]] = {
        "a": {"Domain Users"},
    }
    sizes = {"Domain Users": 9000}
    assert lcd({"a"}, user_groups, sizes, excluded=set(), floor=500) is None


def test_lcd_single_user_under_floor_returns_group() -> None:
    user_groups: dict[str, frozenset[str] | set[str]] = {
        "a": {"SmallTeam"},
    }
    sizes = {"SmallTeam": 7}
    assert lcd({"a"}, user_groups, sizes, excluded=set(), floor=500) == "SmallTeam"


def test_lcd_deterministic_tiebreak_on_group_id() -> None:
    user_groups: dict[str, frozenset[str] | set[str]] = {
        "a": {"A", "B"},
        "b": {"A", "B"},
    }
    sizes = {"A": 10, "B": 10}
    assert lcd({"a", "b"}, user_groups, sizes, excluded=set()) == "A"


def test_lcd_returns_none_when_user_missing_from_user_groups() -> None:
    # Runtime guard: a user with no entry cannot contribute to an intersection.
    user_groups: dict[str, frozenset[str] | set[str]] = {"a": {"Sales"}}
    sizes = {"Sales": 20}
    assert lcd({"a", "b"}, user_groups, sizes, excluded=set()) is None


def test_aggregator_buckets_rows_into_lcd_strands() -> None:
    agg = GroupAggregator(excluded={"Everyone"}, single_user_floor=500)
    sizes = {"Sales": 50, "Everyone": 10000}
    rows: list[dict[str, Any]] = [
        {
            "user_upn": "a",
            "groups": frozenset({"Sales", "Everyone"}),
            "dst": "app:m365",
            "bytes": 100,
            "flows": 1,
        },
        {
            "user_upn": "b",
            "groups": frozenset({"Sales", "Everyone"}),
            "dst": "app:m365",
            "bytes": 200,
            "flows": 2,
        },
    ]
    links = agg.aggregate(rows, group_sizes=sizes, group_by="group")
    matches = [
        link
        for link in links
        if link["src"] == "Sales" and link["dst"] == "app:m365"
    ]
    assert len(matches) == 1
    assert matches[0]["users"] == 2
    assert matches[0]["bytes"] == 300
    assert matches[0]["flows"] == 3


def test_aggregator_routes_unknown_users_to_unknown_strand() -> None:
    agg = GroupAggregator(excluded=set(), single_user_floor=500)
    rows: list[dict[str, Any]] = [
        {
            "user_upn": "unknown",
            "groups": frozenset(),
            "dst": "app:m365",
            "bytes": 1,
            "flows": 1,
        }
    ]
    links = agg.aggregate(rows, group_sizes={}, group_by="group")
    assert any(link["src"] == "unknown" for link in links)


def test_aggregator_lcd_miss_produces_per_user_strands() -> None:
    agg = GroupAggregator(excluded={"Everyone"}, single_user_floor=500)
    sizes = {"Everyone": 9999}
    rows: list[dict[str, Any]] = [
        {
            "user_upn": "a",
            "groups": frozenset({"Everyone"}),
            "dst": "app:m365",
            "bytes": 5,
            "flows": 1,
        },
        {
            "user_upn": "b",
            "groups": frozenset({"Everyone"}),
            "dst": "app:m365",
            "bytes": 6,
            "flows": 1,
        },
    ]
    links = agg.aggregate(rows, group_sizes=sizes, group_by="group")
    srcs = {link["src"] for link in links}
    assert srcs == {"a", "b"}
