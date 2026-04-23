# ZTNA Flow Discovery — Plan 2: Flow Pipeline MVP

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-04-22-ztna-flow-discovery-design.md`
**Prereq plan:** `docs/superpowers/plans/2026-04-22-ztna-p1-foundation.md` (merged to `main` — Traefik, TimescaleDB with full schema, Redis, Alembic migrate sidecar, api stub with `/health/*`, CI pipeline all exist).
**Downstream context:** `docs/superpowers/plans/2026-04-22-ztna-p4-polish-ops.md` — auth, observability, load testing, E2E Playwright, supply-chain scans, backups, ops runbooks are P4 deliverables. P2 stubs the integration points and marks TODOs.

**Goal:** Stand up the flow-only MVP of the Sankey pipeline end-to-end — syslog in at Traefik, parsed + normalized by `flow-ingest`, PTR-enriched by `resolver`, windowed + app-resolved + persisted by `correlator`, served through expanded REST + WS endpoints on `api`, rendered live by a React SPA — such that an operator can point a Palo Alto or FortiGate firewall at the syslog entrypoint and see a live Sankey inside 10 minutes.

**Architecture:** Three new Python asyncio services join the P1 stack on the `backend` Docker network. `flow-ingest` runs vendor-specific parsers behind a shared `SyslogReceiver`, demuxes PAN vs FortiGate by source IP, and publishes normalized `FlowEvent`s to Redis stream `flows.raw`. `resolver` consumes `dns:unresolved`, does async PTR lookups, and caches results in Redis + `dns_cache`. `correlator` pulls `flows.raw`, runs a bounded-queue pipeline (FlowWindower → AppResolver → Writer) that writes 5s-aggregated rows to the `flows` hypertable and pushes `SankeyDelta` messages to Redis pub/sub `sankey.live`. The `api` service gains routers (`flows`, `applications`, `saas`, `adapters`, `ws`) and serves the new React 19 + Vite + `d3-sankey` SPA (prod: bundled static; dev: separate Vite). Traefik gains TCP/UDP routers wiring the `firewall-syslog-*` entrypoints to `flow-ingest`. A dev-profile `mock-syslog-generator` synthesizes PAN + FGT log lines so the whole stack can be exercised without a real firewall. Identity (`id-ingest`, LCD grouping) and auth/observability are deliberately deferred — the Sankey left column is `src_ip` in P2.

**Tech Stack:**
- **Services (Python 3.12, asyncio):** `uvloop`, `redis` 5.x async, `asyncpg` for COPY, `pydantic-settings`, `loguru`, `PyYAML`, `aiodns` (bundled for PTR).
- **api:** FastAPI 0.115 (already present), adds `fastapi-pagination` cursor helpers (hand-rolled), WebSocket fan-out via Redis pub/sub.
- **web:** React 19, TypeScript 5.6, Vite 5, Tailwind CSS 3, TanStack Query 5, Zustand, `d3-sankey` 0.12, `d3-selection`, `d3-scale`, Vitest + React Testing Library.
- **Testing:** pytest + `pytest-asyncio`, `pytest-redis`, `testing.postgresql` (spins ephemeral PG for router tests), golden-log fixtures, Playwright (smoke only — deep E2E is P4).
- **CI:** extends existing `.github/workflows/ci.yml` with Node/web + integration + Playwright jobs.

---

## File Structure

Files created or modified by this plan (grouped by chunk):

```
ztna-discovery/
  docker-compose.yml                                   # MODIFY: add flow-ingest, correlator, resolver services
  docker-compose.dev.yml                               # MODIFY: add mock-syslog-generator under `dev` profile
  .env.example                                         # MODIFY: add P2 tunables (ingest log level, resolver rate)
  config/
    adapters/
      palo_alto.yaml                                   # NEW: per-firewall allowlist + demux source IPs
      fortigate.yaml                                   # NEW: per-firewall allowlist + demux source IPs
  traefik/
    dynamic/
      tcp-udp.yml                                      # MODIFY: wire firewall-syslog-udp/tcp → flow-ingest
  flow-ingest/
    Dockerfile
    pyproject.toml
    src/flow_ingest/
      __init__.py
      main.py                                          # adapter loader, asyncio.gather run loop
      settings.py                                      # pydantic-settings (redis url, config dir, bind addr)
      syslog_receiver.py                               # shared UDP + TCP syslog framing, reconnect, backpressure
      publisher.py                                     # Redis stream publisher (flows.raw), XADD batching
      adapters/
        __init__.py
        base.py                                        # FlowAdapter ABC + FlowEvent TypedDict
        palo_alto_adapter.py                           # PAN-OS TRAFFIC CSV + LEEF parser
        fortigate_adapter.py                           # FortiGate kv parser
    tests/
      __init__.py
      conftest.py
      test_syslog_receiver.py
      test_publisher.py
      test_palo_alto_adapter.py
      test_fortigate_adapter.py
      test_main_loader.py
      fixtures/
        palo_alto/
          traffic_end.csv
          traffic_start.csv                             # expected to be filtered out
          traffic_leef.txt
        fortigate/
          traffic_close.kv
          traffic_non_close.kv                          # expected to be filtered out
  resolver/
    Dockerfile
    pyproject.toml
    src/resolver/
      __init__.py
      main.py
      settings.py
      resolver_worker.py                               # PTR loop, rate limiter, saas match
      saas_matcher.py                                  # pattern lookup, priority ordering
    tests/
      __init__.py
      conftest.py
      test_resolver_worker.py
      test_saas_matcher.py
  correlator/
    Dockerfile
    pyproject.toml
    src/correlator/
      __init__.py
      main.py                                          # wires pipeline stages, manages queues
      settings.py
      pipeline/
        __init__.py
        windower.py                                    # 5s tumbling window keyed (src,dst,port,proto)
        app_resolver.py                                # resolution chain + in-memory cache + NOTIFY reload
        writer.py                                      # batched asyncpg COPY into flows hypertable
        sankey_publisher.py                            # emits SankeyDelta to Redis pub/sub sankey.live
        metrics.py                                     # counters + gauges (Prometheus client placeholders)
    tests/
      __init__.py
      conftest.py
      test_windower.py
      test_app_resolver.py
      test_writer.py
      test_sankey_publisher.py
  api/
    pyproject.toml                                     # MODIFY: add websockets + extra test deps
    src/api/
      main.py                                          # MODIFY: mount routers, start WS fan-out
      dependencies.py                                  # NEW: DB session, Redis client, pagination helpers
      cursor.py                                        # NEW: opaque base64 cursor encode/decode
      schemas/
        __init__.py
        flows.py
        applications.py
        saas.py
        adapters.py
        sankey.py
      routers/
        __init__.py
        flows.py                                       # /api/flows/sankey + /api/flows/raw
        applications.py                                # CRUD + /audit
        saas.py                                        # CRUD
        adapters.py                                    # GET /api/adapters, /api/stats
        ws.py                                          # /ws/sankey
      ws_fanout.py                                     # Redis pub/sub → subscribed WS clients, filters
    tests/
      test_flows_router.py
      test_applications_router.py
      test_saas_router.py
      test_adapters_router.py
      test_ws_router.py
      test_cursor.py
      test_ws_fanout.py
  web/
    Dockerfile
    package.json
    tsconfig.json
    vite.config.ts
    tailwind.config.ts
    postcss.config.js
    index.html
    .eslintrc.cjs
    src/
      main.tsx
      App.tsx
      index.css
      api/
        client.ts                                      # fetch wrapper + shared error shape (RFC 9457)
        ws.ts                                          # WS reconnect + message normalizer
        queries.ts                                     # TanStack Query hooks for REST
        types.ts                                       # SankeyDelta, Application, SaaSEntry shapes
      store/
        liveStore.ts                                   # Zustand — last SankeyDelta, freshness, lossy flag
        filterStore.ts                                 # Zustand — src_cidr, dst_app, category, proto, deny_only
      components/
        Header.tsx                                     # mode toggle + time range picker
        FiltersSidebar.tsx
        Sankey.tsx                                     # d3-sankey SVG renderer; canvas fallback >500
        SankeyCanvas.tsx                               # canvas path
        DetailsPane.tsx                                # tabs: Link · Node · Override
        OverrideModal.tsx                              # POST /api/applications
        FreshnessBanner.tsx
      lib/
        theme.ts                                       # Okabe-Ito palette, opacity scale
        a11y.ts                                        # focus-ring helpers, contrast checks
    src/__tests__/
      Sankey.test.tsx
      FiltersSidebar.test.tsx
      FreshnessBanner.test.tsx
      DetailsPane.test.tsx
      OverrideModal.test.tsx
      liveStore.test.ts
  mock-syslog-generator/
    Dockerfile
    pyproject.toml
    src/mockgen/
      __init__.py
      main.py                                          # periodic PAN + FGT line generator, UDP send
      templates.py                                     # line format templates per vendor
  tests/
    integration/
      __init__.py
      conftest.py                                      # spins compose.test.yml, waits for services
      test_flow_pipeline_e2e.py                        # syslog in → flows row + WS SankeyDelta out
      fixtures/
        recorded_syslog_stream.txt
    e2e/
      playwright.config.ts
      tests/
        smoke.spec.ts                                  # render + click + override
  compose.test.yml                                     # overlay: deterministic test env (fixed ports, seeds)
  .github/
    workflows/
      ci.yml                                           # MODIFY: add node, python-integration, playwright jobs
```

Responsibilities:

- **`flow-ingest/`** — receives syslog, runs vendor parsers, publishes to Redis. Stateless.
- **`resolver/`** — background PTR worker feeding `dns_cache` + Redis TTL cache. Rate-limited.
- **`correlator/`** — windowing + app resolution + persistence + Sankey fan-out. Pipeline stages with bounded queues; carries lossy flag downstream.
- **`api/`** expansion — every API surface the web SPA calls. **No auth yet**; every mutating route carries `# TODO(P4): require role` markers.
- **`web/`** — React 19 SPA. In prod served as static files by `api`; in dev runs on Vite at `:5173` and proxies `/api` + `/ws` through Traefik (or localhost).
- **`mock-syslog-generator/`** — dev-profile container that drums synthetic PAN + FGT lines at configurable rate to the Traefik `firewall-syslog` entrypoint. Exercises the *full* routing path — not a bypass.
- **Traefik dynamic config** — populates the two TCP + two UDP routers that P1 intentionally left empty.
- **Integration tests + CI** — one harness replays recorded syslog through the real compose stack and asserts both DB rows and WS output. CI gains three parallel jobs.

All Python services share pyproject layouts and the repo-wide `ruff`, `mypy`, `pytest` configs already installed in P1.

---

## Chunk 1: flow-ingest service (adapter framework + PAN + FGT parsers)

<!-- CHUNK-1-PLACEHOLDER -->

---

## Chunk 2: resolver worker (PTR + SaaS matching)

<!-- CHUNK-2-PLACEHOLDER -->

---

## Chunk 3: correlator service (flow-only pipeline)

<!-- CHUNK-3-PLACEHOLDER -->

---

## Chunk 4: api service expansion (routers + WS fan-out)

<!-- CHUNK-4-PLACEHOLDER -->

---

## Chunk 5: web SPA (React 19 + d3-sankey)

<!-- CHUNK-5-PLACEHOLDER -->

---

## Chunk 6: Traefik wiring + mock syslog generator + compose additions

<!-- CHUNK-6-PLACEHOLDER -->

---

## Chunk 7: integration tests + CI extensions

<!-- CHUNK-7-PLACEHOLDER -->

---

## Out of Scope (deferred to P3 / P4)

- **P3 — Identity & LCD grouping.** `id-ingest` service; AD 4624, Entra sign-in, Cisco ISE, Aruba ClearPass adapters; `group-sync` worker; `IdentityIndex` interval tree; `GroupAggregator` LCD algorithm; left-column `group|user` modes; identity-related Redis streams + channels; `/api/identity/resolve`. The correlator pipeline lane for identity is **not** stubbed in P2 — it is added alongside the id-ingest service.
- **P4 — Polish & Ops.** OIDC + JWT + RBAC (`# TODO(P4)` markers left on every mutating route); `/metrics` Prometheus scrape on every service (real counters — P2 uses placeholders); Grafana dashboards; `locust` 20k flows/s load test; deep Playwright E2E with login + screenshots; supply-chain (`pip-audit`, `npm audit`, `trivy`); `pg_dump` backup cron; ops runbooks; traefik `forwardAuth` on dashboard.
