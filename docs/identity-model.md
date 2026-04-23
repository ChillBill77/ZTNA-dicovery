# Identity & LCD Algorithm Reference

This document describes the semantics used by `id-ingest`, the correlator's
identity stages, and the api to turn a raw flow (`src_ip`, `ts`) into a
"**which user** or **which group of users** is behind this traffic?" answer.
It is the spec extract operators need at 3 AM — not a full design doc. See
[`docs/superpowers/specs/2026-04-22-ztna-flow-discovery-design.md`](superpowers/specs/2026-04-22-ztna-flow-discovery-design.md)
for the underlying design.

---

## 1. Confidence ranking

Each `IdentityEvent` carries a `confidence` in [0, 100]. When multiple
bindings overlap on the same `(src_ip, t)`, the highest confidence wins.

| Source                                     | Confidence | Rationale                                                                                |
|--------------------------------------------|------------|------------------------------------------------------------------------------------------|
| Cisco ISE RADIUS Accounting (802.1X)       | 95         | Actively maintained network session; MAC + user bound at authentication time.            |
| Aruba ClearPass (802.1X / CEF)             | 95         | Same as ISE.                                                                             |
| AD Event 4624, LogonType 2 (Interactive)   | 90         | User physically at the console; strong signal user → host.                               |
| AD Event 4624, LogonType 10 (RemoteInt.)   | 90         | RDP session; same binding strength as interactive.                                       |
| Entra sign-in, IP ∈ `ENTRA_CORP_CIDRS`     | 80         | Corp-network Entra auth is a strong signal the user is on that IP (subject to NAT).      |
| AD Event 4624, LogonType 3 (Network)       | 70         | User accessed a share/service from the IP but may not be at the host.                    |
| AD Event 4624, LogonType 11 (Cached)       | 50         | Offline-cached credential — user may be physically present but signal is weaker.         |
| Entra sign-in, IP ∉ `ENTRA_CORP_CIDRS`     | 40         | External IP; could be VPN, NAT, etc. — bind only if nothing stronger is available.       |

**Operators:** tune via the adapter implementation if your environment
differs. For Entra in particular, `ENTRA_CORP_CIDRS` is the single knob that
moves external sign-ins to full 80.

---

## 2. TTL semantics

Each `IdentityEvent` carries a `ttl_seconds`. The interval for a binding is
`[ts, ts + ttl_seconds)` — not `(..., now)`. TTL is anchored on the event
timestamp, not adapter processing time, so out-of-order or late syslog does
not unfairly extend validity.

**Stop events** (RADIUS Accounting Stop from ISE/ClearPass) carry
`event_type="nac-auth-stop"` and `ttl_seconds=0`. When the `IdentityIndex`
sees one, it **removes all prior intervals** for that `(src_ip, user_upn)`
pair rather than inserting a new zero-length interval.

**Expiry** is lazy: the tree is not actively swept. A `resolve(ip, at)` call
drops any interval whose end ≤ `at.timestamp()` before searching. This keeps
insertion O(log n) and makes eviction proportional to read volume.

---

## 3. Resolution algorithm

Implemented in
[`correlator/src/correlator/pipeline/identity_index.py`](../correlator/src/correlator/pipeline/identity_index.py).

```
resolve(ip, at) -> Binding | None:
    tree = trees[ip]
    if tree is None: return None

    # Lazy expiry
    for iv in tree:
        if iv.end <= at: tree.remove(iv)
    if tree is empty:
        trees.pop(ip)
        return None

    # Candidates containing `at`
    hits = tree[at]       # intervals overlapping `at`
    if hits is empty: return None

    # Pick highest confidence, tiebreak on most recent t_start
    return max(hits, key=lambda iv: (iv.confidence, iv.t_start))
```

When `resolve(ip, at)` returns `None`, the flow is labeled `user_upn="unknown"`
by the `Enricher` and routed to the amber "unknown" strand in the Sankey.

---

## 4. LCD (Largest Common Denominator) algorithm

Implemented in
[`correlator/src/correlator/pipeline/group_aggregator.py`](../correlator/src/correlator/pipeline/group_aggregator.py).
Per destination and per 5 s window, the correlator has a set of contributing
users `U`. It must pick a single label for the Sankey left column.

```
lcd(users U, user_groups ug, group_size sz, excluded, floor) -> group | None:
    if U is empty: return None
    if any u in U has no entry in ug: return None

    candidates = intersection of ug[u] for each u in U, minus excluded
    if candidates is empty: return None

    chosen = argmin_g in candidates (sz[g], g)    # smallest size, lex tiebreak
    if |U| == 1 and sz[chosen] > floor: return None   # too broad for a single user

    return chosen
```

### Fallback cascade

If `lcd(...)` returns `None`, the aggregator falls back in this order:

1. **Unknown users** are always routed to a separate `"unknown"` strand,
   regardless of the outcome for known users.
2. **LCD miss** (no candidates) → render **per-user strands**. Each user_upn
   becomes its own left-column label. A `reason="lcd_miss"` hint is attached
   so the UI can annotate the badge.
3. **Single-user above `floor`** → same as above (per-user strand) with
   `reason="single_user_floor"`.

### Caching

The aggregator caches the LCD decision by `frozenset(users)` per window.
Identical user sets across multiple destinations in the same tick compute LCD
once. The cache is cleared on `NOTIFY groups_changed` so membership updates
propagate to the next window.

---

## 5. Excluded groups

Default exclusions (configured via `EXCLUDED_GROUPS`):

| Group                  | Reason for exclusion                                                     |
|------------------------|--------------------------------------------------------------------------|
| `Domain Users`         | Every AD user is a member — never narrows the denominator.               |
| `Authenticated Users`  | All authenticated principals — equivalent to `Domain Users` for humans.  |
| `Everyone`             | Tautological; always in the intersection.                                |

Operators can extend the list (e.g., `Licensed Users`, company-wide M365
security groups) via the correlator setting:

```bash
# docker-compose env / .env
EXCLUDED_GROUPS=Domain Users,Authenticated Users,Everyone,All Employees
```

`single_user_floor` (default 500) is the threshold above which a
single-user LCD result is discarded. Raise it if your organization's
"smallest meaningful team" exceeds 500 members.

---

## 6. Group membership freshness

- **Nightly full scan** — `group-sync` worker runs `sync_all()` across every
  configured adapter (AD LDAP + Entra Graph) at `GROUP_SYNC_FULL_CRON`
  (default `0 2 * * *`).
- **On-demand per-user** — when a UPN appears in `identity.events` for the
  first time this process lifetime, the worker fires `sync_user(upn)`
  synchronously so a live flow doesn't wait for the next nightly pass.
- **Reload path** — after `sync_all` completes, the `GroupChangeNotifier`
  refreshes the `group_members` materialized view and issues
  `NOTIFY groups_changed`. The correlator's `GroupIndex.listen_for_changes`
  is subscribed; it reloads the in-memory maps and clears the LCD cache.

**Staleness tolerance:** 24 h acceptable; alert at 48 h via `/api/stats`
field `group_sync_age_seconds`.

---

## 7. Metric glossary

Exposed via `prometheus_client` (P4 observability):

| Metric                                         | Kind    | Meaning                                                                              |
|------------------------------------------------|---------|--------------------------------------------------------------------------------------|
| `correlator_unknown_user_ratio`                | gauge   | Fraction of enriched flows in the last window with `user_upn=="unknown"`.           |
| `correlator_lcd_miss_total`                    | counter | Incremented each time LCD returned `None` and the aggregator fell back to per-user. |
| `identity_index_size`                          | gauge   | Sum of interval-tree entries across all `src_ip` trees in the IdentityIndex.        |
| `group_sync_last_full_cycle_seconds`           | gauge   | Wall-clock duration of the last nightly `sync_all` cycle.                           |
| `id_ingest_events_total{adapter}`              | counter | Events emitted per identity adapter.                                                |
| `id_ingest_parse_errors_total{adapter}`        | counter | Parse failures per adapter (malformed lines / unexpected schema).                   |
| `id_ingest_source_ip_mismatch_total{adapter}`  | counter | Syslog lines dropped because `allowed_sources` filter rejected the peer IP.         |

Alert ideas:

- `correlator_unknown_user_ratio > 0.5` for 10 minutes → identity-source outage.
- `group_sync_age_seconds > 48h` → group-sync stalled (LDAP/Graph down or misauthenticated).
- `identity_index_size` saturating (e.g., > 10 × typical) → stop events not arriving.
