from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def lcd(
    users: set[str],
    user_groups: dict[str, frozenset[str] | set[str]],
    group_size: dict[str, int],
    excluded: set[str],
    floor: int = 500,
) -> str | None:
    """Largest-common-denominator group across ``users``.

    Returns the group id whose membership contains every user, excluding
    ``excluded``, minimizing group size, and tiebreaking on group id
    lexicographically for determinism. Returns ``None`` when:
      - ``users`` is empty
      - any user has no entry in ``user_groups``
      - the intersection (minus excluded) is empty
      - a single-user caller's only candidate exceeds ``floor``
    """

    if not users:
        return None
    try:
        sets = [set(user_groups[u]) for u in users]
    except KeyError:
        return None
    candidates = set.intersection(*sets) - excluded if sets else set()
    if not candidates:
        return None
    chosen = min(candidates, key=lambda g: (group_size.get(g, 0), g))
    if len(users) == 1 and group_size.get(chosen, 0) > floor:
        return None
    return chosen


class GroupAggregator:
    """Bucket enriched rows into Sankey links keyed by LCD group or fallback."""

    def __init__(self, *, excluded: set[str], single_user_floor: int = 500) -> None:
        self._excluded = excluded
        self._floor = single_user_floor
        self._cache: dict[frozenset[str], str | None] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def aggregate(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        group_sizes: dict[str, int],
        group_by: str = "group",
    ) -> list[dict[str, Any]]:
        per_dst_users: dict[str, set[str]] = defaultdict(set)
        per_dst_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        ug: dict[str, frozenset[str]] = {}
        for r in rows:
            upn = r["user_upn"]
            per_dst_users[r["dst"]].add(upn)
            per_dst_rows[r["dst"]].append(r)
            ug[upn] = frozenset(r.get("groups") or frozenset())

        links: dict[tuple[str, str], dict[str, Any]] = {}
        for dst, users in per_dst_users.items():
            known = {u for u in users if u != "unknown"}
            unknown = users - known

            # UNKNOWN strand — always kept separate.
            if unknown:
                for r in per_dst_rows[dst]:
                    if r["user_upn"] == "unknown":
                        _accum(links, "unknown", dst, r)

            if not known:
                continue

            if group_by == "user":
                label_for: dict[str, str] = {u: u for u in known}
            elif group_by == "src_ip":
                label_for = {}
                for r in per_dst_rows[dst]:
                    if r["user_upn"] != "unknown":
                        label_for[r["user_upn"]] = str(r.get("src_ip", r["user_upn"]))
            else:
                key = frozenset(known)
                if key not in self._cache:
                    self._cache[key] = lcd(
                        set(known),
                        {u: ug[u] for u in known},
                        group_sizes,
                        excluded=self._excluded,
                        floor=self._floor,
                    )
                chosen = self._cache[key]
                # chosen=None → per-user fallback; otherwise rollup to chosen group.
                label_for = {u: u for u in known} if chosen is None else {u: chosen for u in known}

            for r in per_dst_rows[dst]:
                if r["user_upn"] == "unknown":
                    continue
                src_label = label_for[r["user_upn"]]
                _accum(links, src_label, dst, r)

        # Finalize `users` as count (live set was used only during accumulation).
        return [_finalize(link) for link in links.values()]


def _accum(
    links: dict[tuple[str, str], dict[str, Any]],
    src: str,
    dst: str,
    row: dict[str, Any],
) -> None:
    key = (src, dst)
    link = links.get(key)
    if link is None:
        link = {
            "src": src,
            "dst": dst,
            "bytes": 0,
            "flows": 0,
            "_users": set(),
        }
        links[key] = link
    link["bytes"] += int(row.get("bytes", 0))
    link["flows"] += int(row.get("flows", row.get("flow_count", 1)))
    link["_users"].add(row["user_upn"])


def _finalize(link: dict[str, Any]) -> dict[str, Any]:
    live: set[str] = link.pop("_users")
    link["users"] = len(live)
    return link
