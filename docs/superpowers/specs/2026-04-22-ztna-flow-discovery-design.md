# ZTNA Flow Discovery — Design Spec

**Status:** Draft for review
**Date:** 2026-04-22
**Owner:** gvanheyst
**Repo:** ZTNA-dicovery

---

## 1. Problem & Goals

### Situation–Complication–Question

**Situation.** Organizations are adopting Zero Trust Network Access (ZTNA) frameworks, but their transition depends on first mapping the existing network reality: which users and user groups access which applications. Today, firewalls log these flows and SIEMs ingest them, but the data remains fragmented in raw logs without identity context or group-level abstraction.

**Complication.** The visibility gap spans across the entire organization. Network administrators see flows but lack user identity context — they cannot answer "who is accessing this?" without manual correlation. Product owners and application teams are often unaware who accesses their applications at all, creating gaps in ownership and responsibility. Current firewall consoles and SIEM dashboards surface raw transaction logs but cannot bridge these silos. Legacy applications compound the problem: without documented ownership, it is unclear even who should be designing policy for them. Large application segments resist granular partitioning because there is no clear data showing which user groups actually need access to which sub-components. This fragmentation — network view without identity, identity systems without application context, and applications without known users — blocks the unified, identity-aware, group-level view required to design defensible Zero Trust policies.

**Question.** How can the organization establish a live, group-aware baseline of network flows enriched with identity data, so policy designers can see at a glance which users and groups access which applications — and move from guesswork to evidence-based zero-trust policy design?

### Overview

Organizations rolling out Zero Trust Network Access (ZTNA) need to first **see** what exists: which endpoints (source computers / users) communicate with which applications (destination servers and ports). Current firewall consoles and SIEM dashboards surface raw logs but don't give a live, identity-aware, group-level view suitable for policy design discussions.

This project delivers a self-hosted web application that visualizes network flows as a **near-realtime Sankey diagram**, enriched with user and group identity from Entra ID / on-prem Active Directory / NAC systems, so teams can see at a glance "which groups of users access which applications".

### Primary goals

1. **Flow visibility** — ingest firewall flow logs, present aggregated source → destination bytes as a Sankey, with ≤ 5s refresh in live mode and minute-granularity historical analysis.
2. **Identity enrichment** — correlate source IPs with users via AD, Entra ID, Cisco ISE, Aruba ClearPass. Present the largest common group denominator (LCD) that covers all users reaching a given destination.
3. **Application labeling** — auto-label destinations using firewall-supplied App-ID, PTR reverse DNS, and a curated SaaS catalog; allow manual overrides for internal apps.
4. **Pluggable architecture** — new flow sources (NetFlow, eBPF, VPC flow logs, SIEM) and identity sources (DHCP, Intune, other NACs) drop in as adapter plugins without core changes.

### Non-goals

- Active network scanning or reconnaissance (no nmap/port-scan functionality).
- Policy enforcement — this is a discovery/visualization tool, not a ZTNA gateway.
- Packet capture / DPI — rely on existing firewall / network logs.
- Multi-tenant SaaS delivery — single-organization self-hosted.

### Success criteria

- Operator can deploy via `docker compose up -d` on a single Linux host.
- Within 10 minutes of pointing a Palo Alto or FortiGate at syslog, the Sankey shows live flows.
- Within a further 15 minutes of connecting AD / Entra / ISE / ClearPass, user and group enrichment appears.
- Ingest sustains **20,000 flows/s peak** across 1,000 endpoints without drops.
- Live mode end-to-end latency (flow arrival → UI render) ≤ 5 s at steady state.

---

## 2. Scope Summary

| Dimension | Value |
|---|---|
| Deployment target | Docker Compose on a single Linux host |
| Scale target | 1,000 endpoints, 20,000 flows/s peak |
| Data retention | 30 days, enforced by Timescale retention policy |
| Live latency | ≤ 5 s (WebSocket push) |
| Historical granularity | 60 s continuous aggregates |
| Day-1 flow adapters | Palo Alto PAN-OS syslog, FortiGate syslog |
| Day-1 identity adapters | AD event 4624, Entra ID sign-in logs (Graph), Cisco ISE, Aruba ClearPass |
| Auth | OIDC via Entra ID; roles viewer / editor / admin |

---

## 3. Architecture

### 3.1 Service topology (7 runtime containers + migrate sidecar)

```
                   ┌──────────────────────────────────────────┐
                   │                Traefik                   │
                   │  edge router / TLS / UDP+TCP routers     │
                   │                                          │
                   │  :443 HTTPS (web, api, /ws)              │
                   │  :514 UDP/TCP  → flow-ingest (PAN/FGT)   │
                   │  :516 UDP/TCP  → id-ingest (AD 4624)     │
                   │  :517 UDP/TCP  → id-ingest (ISE)         │
                   │  :518 UDP/TCP  → id-ingest (ClearPass)   │
                   └──────┬──────────────┬────────────────┬───┘
                          │              │                │
┌─────────────────────────┼──────────────┼────────────────┼───────────┐
│                 Docker Compose host (backend network)              │
│         ▼                         ▼                 ▼              │
│  ┌──────────────┐          ┌────────────┐    ┌────────────────┐    │
│  │ flow-ingest  │          │ id-ingest  │    │ correlator     │    │
│  │  (Python)    │          │  (Python)  │    │  (Python)      │    │
│  │              │          │            │    │ - window join  │    │
│  │ adapters:    │          │ adapters:  │    │ - LCD groups   │    │
│  │  - palo-alto │          │  - ad-4624 │    │ - aggregate    │    │
│  │  - fortigate │          │  - entra   │    │                │    │
│  │              │          │  - ise     │    │                │    │
│  │              │          │  - cpass   │    │                │    │
│  └──────┬───────┘          └──────┬─────┘    └────────┬───────┘    │
│         │                         │                   ▲            │
│         ▼                         ▼                   │            │
│       ┌──────────────────────┐                        │            │
│       │  Redis Streams (bus) │────────────────────────┘            │
│       └──────────┬───────────┘                                     │
│                  ▼                                                 │
│       ┌───────────────────────────┐                                │
│       │ TimescaleDB (Postgres 16) │                                │
│       │  - flows (hypertable)     │                                │
│       │  - identity_events        │                                │
│       │  - user_groups            │                                │
│       │  - applications           │                                │
│       │  - saas_catalog           │                                │
│       │  - continuous aggregates  │                                │
│       └──────────┬────────────────┘                                │
│                  │                                                 │
│         ┌────────┴────────┐                                        │
│         ▼                 ▼                                        │
│  ┌─────────────┐    ┌──────────────┐                               │
│  │ api (FastAPI)│──►│ web (React+TS│                               │
│  │  REST + WS   │   │  + D3 Sankey)│                               │
│  └─────────────┘    └──────────────┘                               │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 Responsibilities

- **traefik** — single edge router. Terminates TLS (Let's Encrypt or provided cert) for `web`/`api`/`/ws` on :443, multiplexes by path prefix (`/`, `/api`, `/ws`). Also hosts TCP/UDP routers for syslog entrypoints (:514/:516/:517/:518) → forwards raw to internal services. All host-published ports funnel through Traefik; backend services expose no host ports.
- **flow-ingest** — one listener per flow adapter; parses, normalizes, publishes `flows.raw` to Redis. No persistence.
- **id-ingest** — runs identity adapters (pull for Entra via Graph API delta, push for AD/ISE/ClearPass syslog); publishes `identity.events` to Redis. Also runs `group-sync` worker which populates `user_groups` from AD LDAP and Entra Graph.
- **correlator** — consumes both Redis streams; windows flows to 5 s tuples; enriches with identity + app label; computes LCD group per (user-set, destination); writes aggregated rows to Postgres; pushes `SankeyDelta` to `sankey.live` Redis pub/sub.
- **postgres (timescaledb)** — time-series storage for flows + identity events; relational storage for catalogs.
- **redis** — message bus (Streams) + pub/sub for WS fan-out + short-lived caches (DNS, group membership).
- **api** — FastAPI; REST for historical / CRUD; WebSocket for live Sankey fan-out; JWT/OIDC auth; RBAC.
- **web** — React 19 + TS + D3 Sankey SPA; served by `api` at `/` in prod, separate Vite dev server in development.
- **migrate** — Alembic migrations; runs `upgrade head` on stack start, exits.

### 3.3 Plugin boundary

`flow-ingest` and `id-ingest` each scan an `adapters/` directory, import all `*_adapter.py` modules, instantiate classes extending `FlowAdapter` / `IdentityAdapter`, and run them concurrently with `asyncio.gather`. Each adapter loads its own YAML config from `/etc/flowvis/adapters/<name>.yaml`. **Adding a new source = drop a file, ship a config, restart.**

---

## 4. Data Model

### 4.1 Flow storage

```sql
CREATE TABLE flows (
  time        TIMESTAMPTZ NOT NULL,
  src_ip      INET        NOT NULL,
  dst_ip      INET        NOT NULL,
  dst_port    INT         NOT NULL,
  proto       SMALLINT    NOT NULL,
  bytes       BIGINT      NOT NULL,
  packets     BIGINT      NOT NULL,
  flow_count  INT         NOT NULL,
  source      TEXT        NOT NULL    -- adapter name, e.g. 'palo_alto' | 'fortigate' (NOT firewall hostname)
);
SELECT create_hypertable('flows', 'time', chunk_time_interval => INTERVAL '1 hour');
SELECT add_retention_policy('flows', INTERVAL '30 days');
CREATE INDEX ON flows (src_ip, time DESC);
CREATE INDEX ON flows (dst_ip, dst_port, time DESC);

CREATE MATERIALIZED VIEW flows_1m
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket,
       src_ip, dst_ip, dst_port, proto,
       sum(bytes) AS bytes, sum(packets) AS packets, sum(flow_count) AS flow_count
FROM flows GROUP BY bucket, src_ip, dst_ip, dst_port, proto;
SELECT add_continuous_aggregate_policy('flows_1m',
  start_offset => INTERVAL '3 hours',
  end_offset   => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');
```

### 4.2 Identity

```sql
CREATE TABLE identity_events (
  time         TIMESTAMPTZ NOT NULL,
  src_ip       INET        NOT NULL,
  user_upn     TEXT        NOT NULL,
  source       TEXT        NOT NULL,
  confidence   SMALLINT    NOT NULL,
  ttl_seconds  INT         NOT NULL,
  event_type   TEXT        NOT NULL,
  raw_id       TEXT
);
SELECT create_hypertable('identity_events', 'time', chunk_time_interval => INTERVAL '1 hour');
SELECT add_retention_policy('identity_events', INTERVAL '30 days');
CREATE INDEX ON identity_events (src_ip, time DESC);
CREATE INDEX ON identity_events (user_upn, time DESC);

CREATE TABLE user_groups (
  user_upn     TEXT        NOT NULL,
  group_id     TEXT        NOT NULL,
  group_name   TEXT        NOT NULL,
  group_source TEXT        NOT NULL,   -- 'ad' | 'entra'
  refreshed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (user_upn, group_id)
);
CREATE INDEX ON user_groups (group_id);

CREATE MATERIALIZED VIEW group_members AS
  SELECT group_id, group_name, array_agg(user_upn ORDER BY user_upn) AS members, count(*) AS size
  FROM user_groups GROUP BY group_id, group_name;
CREATE INDEX ON group_members (group_id);
```

**Confidence ranking (default, tunable per adapter config):**

| Source | Confidence | TTL default |
|---|---|---|
| Cisco ISE 802.1X (active session) | 95 | from Session-Timeout, else 12 h |
| Aruba ClearPass 802.1X (active) | 95 | same |
| AD 4624 interactive logon (types 2, 10, 11) | 90 | 8 h |
| Entra sign-in, IP in `corp_cidrs` | 80 | 1 h |
| AD 4624 network logon (type 3) | 70 | 8 h |
| AD 4624 cached / other | 50 | 8 h |
| Entra sign-in, IP outside `corp_cidrs` | 40 | 1 h |

Correlator resolves `(src_ip, flow_time)` by selecting the binding with the highest confidence within its TTL window.

### 4.3 Application & SaaS catalogs

```sql
CREATE TABLE applications (
  id            SERIAL       PRIMARY KEY,
  name          TEXT         NOT NULL,
  description   TEXT,
  owner         TEXT,
  dst_cidr      CIDR         NOT NULL,
  dst_port_min  INT,
  dst_port_max  INT,
  proto         SMALLINT,
  priority      INT          NOT NULL DEFAULT 100,
  source        TEXT         NOT NULL DEFAULT 'manual',
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_by    TEXT
);
CREATE INDEX ON applications USING gist (dst_cidr inet_ops);
CREATE INDEX ON applications (priority DESC);

CREATE TABLE application_audit (
  id              BIGSERIAL   PRIMARY KEY,
  application_id  INT         NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  changed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  changed_by      TEXT        NOT NULL,
  op              TEXT        NOT NULL,   -- 'create' | 'update' | 'delete'
  before          JSONB,
  after           JSONB
);

CREATE TABLE saas_catalog (
  id             SERIAL PRIMARY KEY,
  name           TEXT    NOT NULL,
  vendor         TEXT,
  fqdn_pattern   TEXT    NOT NULL,     -- suffix match (e.g. '.office365.com')
  category       TEXT,
  source         TEXT    NOT NULL DEFAULT 'manual',
  priority       INT     NOT NULL DEFAULT 100
);
CREATE INDEX ON saas_catalog (fqdn_pattern);

CREATE TABLE dns_cache (
  dst_ip       INET        PRIMARY KEY,
  ptr          TEXT,                      -- NULL = NXDOMAIN
  resolved_at  TIMESTAMPTZ NOT NULL,
  ttl_seconds  INT         NOT NULL DEFAULT 3600,
  source       TEXT        NOT NULL      -- 'ptr' | 'firewall-log'
);

CREATE TABLE port_defaults (
  port   INT      NOT NULL,
  proto  SMALLINT NOT NULL,
  name   TEXT     NOT NULL,
  PRIMARY KEY (port, proto)
);
```

**Destination resolution priority (in correlator):**

1. **Manual `applications`** — most specific CIDR + highest priority wins.
2. **Firewall-supplied FQDN / App-ID** — from PAN App-ID or FortiGate `hostname`/`app`; matched against `saas_catalog.fqdn_pattern` (suffix match).
3. **PTR reverse DNS** — async via `resolver` worker, cached in Redis + `dns_cache`; matched against `saas_catalog`.
4. **Port default** — from `port_defaults` (HTTPS, SSH, RDP, …).
5. **Raw `ip:port`**.

SaaS seed list (~50 entries) ships in a migration: `office365.com`, `sharepoint.com`, `salesforce.com`, `github.com`, `slack.com`, `zoom.us`, `atlassian.net`, `googleapis.com`, `amazonaws.com`, etc.

---

## 5. Adapter Interfaces

### 5.1 Flow adapter

```python
class FlowEvent(TypedDict):
    ts: datetime
    src_ip: str; src_port: int
    dst_ip: str; dst_port: int
    proto: int
    bytes: int; packets: int
    action: str                # 'allow' | 'deny' | 'drop'
    fqdn: str | None           # firewall-supplied hostname
    app_id: str | None         # vendor App-ID
    source: str                # adapter name
    raw_id: str | None

class FlowAdapter(ABC):
    name: str
    @abstractmethod
    async def run(self) -> AsyncIterator[FlowEvent]: ...
    @abstractmethod
    def healthcheck(self) -> dict: ...
```

### 5.2 Identity adapter

```python
class IdentityEvent(TypedDict):
    ts: datetime
    src_ip: str
    user_upn: str
    source: str
    event_type: str            # 'logon' | 'dhcp' | 'nac-auth'
    confidence: int            # 0-100
    ttl_seconds: int
    mac: str | None
    raw_id: str | None

class IdentityAdapter(ABC):
    name: str
    @abstractmethod
    async def run(self) -> AsyncIterator[IdentityEvent]: ...
```

### 5.3 Day-1 adapters

| Adapter | Transport | Notes |
|---|---|---|
| `palo_alto_adapter` | syslog UDP/TCP, CSV or LEEF | TRAFFIC logs; keep `log_subtype=end` only to avoid double-counting; App-ID → `app_id` field |
| `fortigate_adapter` | syslog UDP/TCP, key=value | `type=traffic,subtype=forward,status=close`; `hostname`, `app` → `fqdn`/`app_id` |
| `ad_4624_adapter` | syslog from WEF/Winlogbeat | Event 4624; filter logon types 2/3/10/11; parse `TargetUserName`, `IpAddress` |
| `entra_signin_adapter` | Graph API `auditLogs/signIns`, 60s delta poll | client-credentials auth; `AuditLog.Read.All`; success only; YAML config surface includes `tenant_id`, `client_id`, `client_secret` (env), `corp_cidrs: [CIDR, ...]` used by confidence rules |
| `cisco_ise_adapter` | syslog LiveLogs | RADIUS Accounting Start/Stop; `User-Name`, `Framed-IP-Address` |
| `aruba_clearpass_adapter` | syslog CEF | same pattern as ISE |

A shared `SyslogReceiver` base handles UDP/TCP framing, reconnect, backpressure; adapters implement only `parse(line: bytes) -> Event | None`.

---

## 6. Correlator & LCD Algorithm

### 6.1 Pipeline stages

```
Redis flows.raw ─► FlowWindower (5s tumbling) ─┐
Redis identity  ─► IdentityIndex (interval tree)─┤
                                                ├─► Enricher ─► GroupAggregator(LCD) ─► Writer
Postgres apps ──► AppResolver cache ────────────┘
```

Each stage connected by bounded `asyncio.Queue(maxsize=10000)`. Queue overflow drops oldest and increments `correlator_dropped_flows_total`. **Each `SankeyDelta` carries a `lossy: bool` flag** set when any stage dropped flows during the window, plus a `dropped_count` hint; the UI freshness banner turns amber for lossy windows so users know totals are under-counted.

### 6.2 IdentityIndex

Per `src_ip`, interval tree of `(t_start, t_end, user_upn, confidence, source)`. Lookup for `(src_ip, t)`:

1. Find intervals containing `t`.
2. Pick highest `confidence`; tiebreak = most recent `t_start`.
3. None found → `user_upn = "unknown"`.

Expires past TTL. Memory bound trivial (~5 k entries at 1 k clients).

### 6.3 Largest Common Denominator (LCD) group

**Definition.** Given a set of users `U` all reaching the same destination in a window, and the group catalog `G`, return the group `g ∈ G` such that `U ⊆ members(g)` and `|members(g)|` is minimal; tiebreak deterministically on `group_id`.

```python
def lcd(users: set[str],
        user_groups: dict[str, set[str]],
        group_size: dict[str, int],
        excluded: set[str],
        floor: int = 500) -> str | None:
    if not users: return None
    candidates = set.intersection(*(user_groups[u] for u in users)) - excluded
    if not candidates: return None
    chosen = min(candidates, key=lambda g: (group_size[g], g))
    if len(users) == 1 and group_size[chosen] > floor:
        return None       # fall back to user-level strand
    return chosen
```

**Config knobs:**

- `excluded_groups` — default includes `Domain Users`, `Authenticated Users`, `Everyone`.
- `single_user_floor` — default 500; prevents useless "Domain Users" collapse for lone-user strands.
- `nested` — we use flattened (transitive) membership from the directory.

**Fallback behavior** (in order):

1. **Unknown users** — excluded from LCD computation, rendered as a separate `"unknown"` strand.
2. **Known users with no shared non-excluded group** (LCD returns `None` for the group-set) — rendered as individual per-user strands in the left column, with label = `user_upn`.
3. **Single-user above floor** — same as case 2: rendered as individual user strand.

### 6.4 Sankey delta message

```json
{
  "ts": "2026-04-22T14:12:05Z",
  "window_s": 5,
  "nodes_left":  [{"id": "g:sales-emea", "label": "Sales EMEA", "size": 42}],
  "nodes_right": [{"id": "app:m365",     "label": "Microsoft 365", "kind": "saas"}],
  "links": [
    {"src": "g:sales-emea", "dst": "app:m365", "bytes": 28471282, "flows": 312, "users": 14}
  ]
}
```

### 6.5 Group membership refresh

Worker `group-sync` inside `id-ingest`:

- **AD:** LDAP bind; query `memberOf` with range retrieval; nightly full + on-demand for newly-seen users.
- **Entra:** Graph `users/{id}/transitiveMemberOf`; nightly full + per-user on first sight.
- Writes to `user_groups`, refreshes `group_members` materialized view on complete cycle.
- Emits Postgres `NOTIFY groups_changed` → correlator reloads in-memory group index.

Staleness tolerance: 24 h; alert after 48 h.

---

## 7. API

### 7.1 Authentication & RBAC

- **OIDC** against Entra ID (same tenant as identity source); JWT bearer; session cookie for web.
- Roles:
  - `viewer` — read-only Sankey + drill-down.
  - `editor` — manage `applications` and `saas_catalog`.
  - `admin` — adapter config, retention, user management.
- Enforced per route via FastAPI dependency.

### 7.2 REST

```
GET  /api/flows/sankey?from=&to=&mode=live|historical
     &group_by=group|user|src_ip&exclude_groups=
     &src_cidr=&dst_app=&proto=
       → SankeyDelta
GET  /api/flows/raw?src_ip=&dst_ip=&port=&from=&to=&limit=&cursor=
     # cursor is an opaque base64 token {last_time, last_src_ip, last_dst_ip, last_dst_port};
     # response envelope: { "items": [...], "next_cursor": "..." | null, "total_est": N }
GET  /api/identity/resolve?src_ip=&at=
     → { user_upn, source, confidence, groups[] }

GET/POST/PUT/DELETE /api/applications          # editor
GET                 /api/applications/{id}/audit
GET/POST/PUT/DELETE /api/saas                  # editor

GET  /api/adapters        # health + event rate per adapter
GET  /api/health/live
GET  /api/health/ready
GET  /api/stats           # flows/s, unknown-ratio, redis lag
```

Errors: RFC 9457 problem+JSON with `trace_id`. Rate limits: 60 rps/user REST; 1 WS/user session.

### 7.3 WebSocket

```
WS /ws/sankey?mode=live
  → server pushes SankeyDelta every 5 s
  → client sends filter updates inline (no reconnect)
```

Backed by Redis pub/sub channel `sankey.live`; filters applied server-side per connection.

---

## 8. Web UI

**Stack:** React 19 + TypeScript + Vite + TanStack Query + `d3-sankey` + Tailwind.

### 8.1 Layout

```
┌──────────────────────────────────────────────────────────────┐
│ Header: user · role · [live|historical] · time range         │
├──────┬───────────────────────────────────────────────────────┤
│      │   Sankey canvas (resizable)                           │
│ Side │                                                       │
│ bar  │   left: groups/users    right: applications           │
│ +    ├───────────────────────────────────────────────────────┤
│ filt │   Details pane (tabs: Link · Node · Override)         │
└──────┴───────────────────────────────────────────────────────┘
```

### 8.2 Key behaviors

- **Live / Historical toggle** — live uses WS; historical uses `flows_1m` with time-range picker.
- **Left-column mode** — Groups (LCD) · Users · Source IPs.
- **Filters** — src CIDR, dst app, SaaS category, protocol, deny-only, user, group; all server-side.
- **Hover link** — tooltip with bytes/s, flow count, contributing users.
- **Click link** — details pane with top-10 `(src_ip, user)` pairs + raw flow sample.
- **Click right node** — app metadata + "Override label" modal → writes `applications`; next tick re-labels.
- **Click left node** — group/user card; group members list capped at 200.
- **Unknown-user strand** — amber; banner suggests identity-source checks.
- **Freshness banner** — "Live · 3s behind" / "Historical · 15m window"; warns at >30 s lag.

### 8.3 Performance & accessibility

- D3 diff-only redraws, 400 ms transitions; canvas fallback when links > 500.
- **Server-side top-N cap** — `/api/flows/sankey` and `/ws/sankey` accept `limit` (default 200, max 1000), rank by bytes desc, and return `{ "truncated": bool, "total_links": N }`. Client renders exactly what arrives; sidebar shows "showing 200 of N — refine filters" when truncated. Keeps visible-strand totals consistent (no client-side recompute).
- Okabe-Ito colors; magnitude redundantly encoded via opacity.
- Keyboard-navigable focus rings; contrast ≥ 4.5:1 (WCAG AA).

---

## 9. Testing Strategy

- **Unit (pytest):** adapter golden-log fixtures (committed under `tests/fixtures/<adapter>/`); correlator stages; LCD algorithm edge cases (nested groups, excluded groups, floor, empty sets); resolution chain.
- **Integration (Docker Compose):** `compose.test.yml` overlay; replay recorded syslog via `nc -u`; mock Graph with httpx mock transport; assert rows in `flows` and WS `SankeyDelta` content; override propagation ≤ 2 ticks.
- **E2E (Playwright):** login → Sankey render ≤ 3 s → click link → details populate → override label → updates ≤ 10 s. Runs on PRs touching `web/` or `api/`.
- **Load (locust):** 20 k synthetic flows/s to syslog UDP; assert zero drops, correlator p99 < 500 ms, Postgres CPU < 60 %.
- **CI gates:** extend existing `validate-docker-compose.yml` with `ruff` + `mypy` (Python), `tsc` + `eslint` (web), `pytest` unit + integration, Playwright E2E, `pip-audit` + `npm audit`, `trivy` image scan.

---

## 10. Observability

**Metrics (Prometheus, `/metrics` per service):**

- `flow_ingest_events_total{adapter, source}` / `flow_ingest_parse_errors_total{adapter}`
- `identity_ingest_events_total{adapter}`
- `correlator_queue_depth{stage}` / `correlator_dropped_flows_total`
- `correlator_unknown_user_ratio` / `correlator_lcd_miss_total`
- `api_http_requests_total{route, status}` / `api_ws_connections`
- `postgres_insert_batch_size` / `postgres_flush_duration_seconds`

Bundled Grafana dashboard (JSON in repo); available under Compose profile `observe`.

**Logs:** structured JSON via `loguru`; `trace_id` propagated via W3C `traceparent` through REST and Redis messages; PII hashed at INFO, raw at DEBUG.

**Health endpoints:** `/health/live` (liveness) and `/health/ready` (DB + Redis + last ingest tick < 60 s), wired into Docker Compose healthchecks.

---

## 11. Deployment & Ops

### 11.1 Compose profiles

```yaml
services:
  traefik:        # traefik:v3, edge router / TLS / TCP+UDP routers
  postgres:       # timescale/timescaledb:latest-pg16
  redis:          # redis:7-alpine
  flow-ingest:
  id-ingest:
  correlator:
  api:
  web:            # served by api in prod, separate in dev
  migrate:        # runs `alembic upgrade head`, exits

profiles:
  observe:        # prometheus + grafana
  dev:            # mock syslog generator, hot-reload
```

### 11.1.1 Traefik routing

- **EntryPoints**
  - `websecure` — :443/tcp, TLS
  - `firewall-syslog` — :514/udp + :514/tcp. **Default:** PAN and FortiGate share :514; `flow-ingest` demuxes by source IP (configured per-firewall in adapter YAML). *Variant:* operators who prefer isolation can split into :514 PAN + :515 FGT by adding a second entrypoint and router — off by default to keep code and config paths single.
  - `ad-syslog` — :516/udp + :516/tcp
  - `ise-syslog` — :517/udp + :517/tcp
  - `clearpass-syslog` — :518/udp + :518/tcp
- **HTTP routers** (via Docker labels on `api` and `web`)
  - `Host(<domain>) && PathPrefix(/api)` → `api` service
  - `Host(<domain>) && PathPrefix(/ws)` → `api` service (WS upgrade)
  - `Host(<domain>)` → `web` service (SPA)
- **TCP/UDP routers** — catch-all per entrypoint, forwarded to the corresponding ingest service on the backend network.
- **Certificates** — default Let's Encrypt (HTTP-01 or DNS-01 via env-configured provider); fallback to mounted certs at `/etc/traefik/certs/` for offline/air-gapped installs.
- **Dashboard** — Traefik dashboard exposed at `/traefik` behind the same OIDC auth as `api` (via `forwardAuth` middleware hitting `api`'s `/auth/verify` endpoint), admin role only. *Known dependency:* if `api` is down, the dashboard is locked out. Admin fallback path: `docker compose logs traefik` and direct socket inspection from the host. Documented in `docs/operations.md`.
- **Middleware**
  - `rate-limit` — 60 rps per IP on REST paths.
  - `compression` — gzip/br for static assets.
  - `secure-headers` — HSTS, frame-deny, nosniff, referrer-policy, CSP.

All other services expose only container-network ports; **no host ports besides Traefik's entrypoints**.

### 11.2 Secrets

`.env` loaded by Compose (Entra creds, DB password, AD bind). `.env` already in `.gitignore`; ship `.env.example` with placeholders.

### 11.3 Migrations

Alembic; `migrate` service runs `upgrade head` on stack start and exits. Other services `depends_on: { migrate: { condition: service_completed_successfully } }`.

### 11.4 Backup

`pg_dump` cron sidecar → `outputs/` host volume, daily, 7-day retention. Separate from 30-day flow retention.

### 11.5 Upgrade

`docker compose pull && docker compose up -d` — migrations apply automatically via `migrate` service.

---

## 12. Security

- **Only Traefik publishes host ports** (:443 + syslog entrypoints). All backend services (`api`, `web`, `flow-ingest`, `id-ingest`, `correlator`, `postgres`, `redis`) bind only to the internal Docker network.
- Syslog entrypoints should be reached only from the firewall-management network; host firewall (UFW / nftables) guidance in README to restrict source CIDRs per entrypoint.
- TLS terminated at Traefik; internal hop to `api`/`web` is plain HTTP on the private network.
- Secrets via `.env` / Docker secrets in prod; never in image layers.
- JWT validation via cached JWKS; access token 1 h, refresh 8 h.
- PII (UPN, IP) hashed in INFO logs; raw values DEBUG-only.
- Supply chain: `pip-audit`, `npm audit`, `trivy` in CI.

---

## 13. Project Layout

```
ztna-discovery/
  docker-compose.yml
  docker-compose.dev.yml
  .env.example
  README.md
  traefik/
    traefik.yml            # static config: entrypoints, providers, certs
    dynamic/               # dynamic config: tcp/udp routers, middlewares
  flow-ingest/
    adapters/
      base.py
      syslog_receiver.py
      palo_alto_adapter.py
      fortigate_adapter.py
    main.py
    Dockerfile
  id-ingest/
    adapters/
      base.py
      syslog_receiver.py
      ad_4624_adapter.py
      entra_signin_adapter.py
      cisco_ise_adapter.py
      aruba_clearpass_adapter.py
    group_sync.py
    main.py
    Dockerfile
  correlator/
    pipeline/
      windower.py
      identity_index.py
      enricher.py
      group_aggregator.py   # LCD
      writer.py
    main.py
    Dockerfile
  api/
    routers/
    auth/
    main.py
    Dockerfile
  web/
    src/
    Dockerfile
  migrate/
    alembic/
    env.py
  tests/
    fixtures/
    integration/
    e2e/
  docs/
    superpowers/specs/
    adapters.md
    operations.md
  .github/workflows/      # existing + new ci.yml
```

---

## 14. Open Items / Assumptions Flagged

- "20 k flows/s" interpreted as **per-second peak**. If meant as total-at-one-time, architecture comfortably over-provisioned.
- Entra tenant is assumed to be the same used for user SSO and identity enrichment.
- AD event 4624 forwarding (WEF or Winlogbeat) is set up by the operator; out of scope for this app's runtime code, **but `docs/adapters.md` includes a WEF + Winlogbeat setup runbook** so the "≤ 15 min identity enrichment" success criterion is reachable by a first-time operator.
- Group-membership refresh is nightly + on-demand; real-time membership changes can lag up to 24 h (covered by on-demand path for newly-seen users).
- SaaS catalog seed list is intentionally small; expected to grow via UI edits and community contributions.

---

## 15. Out of Scope (restated)

- Active scanning, DPI, policy enforcement.
- Multi-tenant SaaS hosting of this tool.
- Cross-site federation / multi-cluster correlation.
