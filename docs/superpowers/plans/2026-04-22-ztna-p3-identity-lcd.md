# ZTNA Flow Discovery — Plan 3: Identity + LCD

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-04-22-ztna-flow-discovery-design.md` (§4.2 identity schema, §5.2 identity ABC, §6 correlator + LCD)

**Prior plans:**
- `docs/superpowers/plans/2026-04-22-ztna-p1-foundation.md` (stack skeleton + migrations already on main)
- `docs/superpowers/plans/2026-04-22-ztna-p2-flow-pipeline.md` (flow-ingest, correlator pipeline, api + web MVP)

**Goal:** Land identity enrichment and Largest-Common-Denominator (LCD) group aggregation for the Sankey pipeline — extract a shared `common/` package from the P2 flow-ingest bones, build the `id-ingest` service with four identity adapters (AD 4624, Entra sign-in, Cisco ISE, Aruba ClearPass), add a `group-sync` worker that hydrates `user_groups` from AD LDAP + Entra Graph, extend the correlator with an `IdentityIndex` + `Enricher` + `GroupAggregator` stage implementing LCD per spec §6.3, and surface the new signal through api + web (left-column mode toggle, group tooltips, unknown-strand banner, `/api/identity/resolve`). After P3 operators can point AD/Entra/ISE/ClearPass at the stack and see group-labeled strands instead of raw src IPs.

**Architecture:** A new `id-ingest` Python service is scaffolded alongside P2's `flow-ingest` and its shared syslog/async code is factored into `common/` (editable-install used by both containers). `id-ingest` runs N adapter tasks plus one `group-sync` task under `asyncio.gather`; each adapter pushes `IdentityEvent`s onto Redis Stream `identity.events`. The correlator gains a new `IdentityIndex` (per-`src_ip` interval tree, TTL-expiring, highest-confidence-in-window resolver) and an `Enricher` stage sitting between `AppResolver` and `Writer` in the P2 pipeline; a `GroupAggregator` groups enriched rows into LCD strands using the spec §6.3 algorithm with a cascading fallback (unknown → separate strand, LCD miss → per-user, single-user above floor → per-user). The api exposes `/api/identity/resolve`, extends `/api/flows/sankey` with `group_by=group|user|src_ip` and new filters, and adds `/api/groups/{id}`. Web adds a left-column mode toggle (persisted in URL), a groups/users modal, and an amber unknown-strand banner. Traefik TCP/UDP routers for :516/:517/:518 (AD, ISE, ClearPass) are populated in this plan; :514 already belongs to flow-ingest from P2. All adapters are backed by golden-fixture TDD; LDAP and Graph calls are mocked via `ldap3.Mock` and `httpx.MockTransport`.

**Tech Stack:** Python 3.12, `asyncio`, `redis.asyncio` (Stream producer/consumer + pub/sub), `intervaltree` for the per-IP identity cache, `ldap3` for AD group queries, `httpx` + `msal` for Entra Graph (client credentials + delta tokens), `asyncpg` for Postgres `LISTEN`/`NOTIFY`, `pydantic-settings` for per-adapter config, `apscheduler` for nightly full group sync, `pytest` + `pytest-asyncio` for unit tests, `httpx.MockTransport` + `ldap3.Connection(..., client_strategy=MOCK_SYNC)` for adapter tests, Playwright for web smoke, FastAPI + WebSocket for api, React 19 + TanStack Query + `d3-sankey` for web. Traefik v3 TCP/UDP routers. Docker Compose v2.

---

## File Structure

Files created or modified by this plan:

```
ztna-discovery/
  docker-compose.yml                          # MODIFY: add id-ingest service, bind :516/:517/:518 entrypoints
  docker-compose.dev.yml                      # MODIFY: hot-reload mount for id-ingest + common
  .env.example                                # MODIFY: add AD_*, ENTRA_*, ISE_*, CLEARPASS_* placeholders

  common/                                     # NEW: shared package installable by both ingest services
    pyproject.toml                            # editable install target: `pip install -e common/`
    src/ztna_common/
      __init__.py
      syslog_receiver.py                      # MOVED from flow-ingest (P2); framing + reconnect + backpressure
      adapter_base.py                         # MOVED: FlowAdapter + IdentityAdapter ABCs, healthcheck hook
      event_types.py                          # MOVED: FlowEvent + IdentityEvent TypedDicts
      redis_bus.py                            # MOVED: Redis Stream producer/consumer helpers
      config.py                               # MOVED: pydantic-settings loaders + YAML helpers
      logging_config.py                       # MOVED: loguru structured JSON
    tests/
      test_syslog_receiver.py                 # MOVED
      test_adapter_base.py                    # MOVED
      test_event_types.py                     # MOVED
      test_redis_bus.py                       # MOVED
      test_config.py                          # MOVED

  flow-ingest/                                # MODIFY: switch to `ztna_common` imports (P2 originals move out)
    pyproject.toml                            # MODIFY: depend on -e ../common
    Dockerfile                                # MODIFY: COPY common/ and pip install -e

  id-ingest/                                  # NEW
    pyproject.toml
    Dockerfile
    src/id_ingest/
      __init__.py
      main.py                                 # auto-loads *_adapter.py modules + group-sync worker
      adapters/
        __init__.py
        ad_4624_adapter.py                    # WEF/Winlogbeat syslog; Event 4624; logon types 2/3/10/11
        entra_signin_adapter.py               # Graph auditLogs/signIns delta poll 60s
        cisco_ise_adapter.py                  # RADIUS Acct syslog (Start/Stop)
        aruba_clearpass_adapter.py            # CEF syslog
      group_sync/
        __init__.py
        worker.py                             # asyncio task; reads user_groups seed list; schedules full + on-demand
        ad_sync.py                            # ldap3 bind; memberOf range retrieval
        entra_sync.py                         # Graph users/{id}/transitiveMemberOf
        notifier.py                           # REFRESH MAT VIEW + NOTIFY groups_changed
      redis_io.py                             # publish to identity.events stream
      settings.py                             # pydantic-settings; env + /etc/flowvis/adapters/<name>.yaml
    tests/
      conftest.py                             # fixture loader, httpx + ldap3 mocks
      fixtures/
        ad_4624/                              # golden Windows Event 4624 syslog lines
          type2_interactive.txt
          type3_network.txt
          type10_remote.txt
          type11_cached.txt
          malformed.txt
        entra/
          signins_page1.json
          signins_page2.json
          delta_token.json
          corp_cidr_hit.json
          corp_cidr_miss.json
        cisco_ise/
          acct_start.txt
          acct_stop.txt
          session_timeout.txt
        clearpass/
          cef_start.txt
          cef_stop.txt
        ad_ldap/
          memberof_small.ldif
          memberof_range.ldif                 # memberOf;range=0-1499 / 1500-*
        graph_groups/
          transitive_member_of_page1.json
          transitive_member_of_page2.json
      adapters/
        test_ad_4624_adapter.py
        test_entra_signin_adapter.py
        test_cisco_ise_adapter.py
        test_aruba_clearpass_adapter.py
      group_sync/
        test_ad_sync.py
        test_entra_sync.py
        test_worker.py
        test_notifier.py
      test_main.py                            # auto-load + graceful shutdown

  correlator/                                 # MODIFY: extend P2 pipeline with identity stages
    src/correlator/pipeline/
      identity_index.py                       # NEW
      enricher.py                             # NEW (between AppResolver and Writer)
      group_aggregator.py                     # NEW (LCD + fallback cascade)
      group_index.py                          # NEW (in-memory user→groups, reload on NOTIFY)
    src/correlator/main.py                    # MODIFY: wire identity.events consumer + new stages
    src/correlator/settings.py                # MODIFY: add excluded_groups, single_user_floor, reload channel
    src/correlator/sankey_delta.py            # MODIFY: add `users` count per link, `group_by` mode
    tests/pipeline/
      test_identity_index.py                  # NEW
      test_enricher.py                        # NEW
      test_group_aggregator.py                # NEW — LCD edge cases
      test_group_index.py                     # NEW — NOTIFY reload
    tests/fixtures/identity/
      events_basic.jsonl
      events_mixed_confidence.jsonl
      events_expired_ttl.jsonl

  api/                                        # MODIFY
    src/api/routers/identity.py               # NEW: GET /api/identity/resolve
    src/api/routers/groups.py                 # NEW: GET /api/groups/{id} paginated members
    src/api/routers/flows.py                  # MODIFY: group_by=group|user|src_ip, filters group/user/exclude_groups
    src/api/routers/adapters.py               # MODIFY: list id-ingest adapters
    src/api/routers/stats.py                  # MODIFY: unknown_user_ratio, group_sync_age_seconds
    src/api/models/identity.py                # NEW: pydantic schemas for resolve + group responses
    src/api/services/identity_service.py      # NEW: DB + Redis interactions
    tests/routers/
      test_identity_router.py
      test_groups_router.py
      test_flows_router_group_by.py           # MODIFY (extend)
      test_stats_router.py                    # MODIFY

  web/                                        # MODIFY
    src/components/
      LeftColumnModeToggle.tsx                # NEW: Groups | Users | Source IPs
      GroupNodeTooltip.tsx                    # NEW
      GroupMembersModal.tsx                   # NEW (paginated, cap 200)
      UnknownStrandBanner.tsx                 # NEW (amber >50% unknown for 10min)
      UserNodeDetails.tsx                     # NEW
      LcdFallbackBadge.tsx                    # NEW (inline reason)
    src/hooks/useGroupByMode.ts               # URL-state persistence
    src/hooks/useUnknownRatio.ts              # drives amber banner
    src/pages/SankeyPage.tsx                  # MODIFY: mount toggle + banner + new tooltips
    src/pages/FiltersPanel.tsx                # MODIFY: group multi-select, user free-text, exclude_groups seeded
    src/state/sankey_store.ts                 # MODIFY: groupBy, unknownRatio, excludeGroups
    tests/components/
      LeftColumnModeToggle.test.tsx
      GroupNodeTooltip.test.tsx
      GroupMembersModal.test.tsx
      UnknownStrandBanner.test.tsx
    e2e/
      identity_sankey.spec.ts                 # Playwright smoke — toggle, modal, banner

  traefik/dynamic/tcp-udp.yml                 # MODIFY: populate ad-syslog / ise-syslog / clearpass-syslog routers

  tests/integration/
    test_identity_pipeline.py                 # NEW: replay adapters + flow fixtures; assert Sankey left column
    fixtures/
      identity_scenario_a.yml                 # happy-path group labels
      identity_scenario_b.yml                 # LCD miss → per-user strands
      identity_scenario_c.yml                 # unknown-user amber strand

  docs/
    adapters.md                               # NEW: WEF+Winlogbeat, Entra app reg, ISE LiveLogs, ClearPass CEF
    identity-model.md                         # NEW: confidence ranking, TTL, LCD algorithm, exclusions
```

Responsibilities:

- **`common/`** — single source of truth for code previously duplicated by flow-ingest and needed by id-ingest. Editable install keeps dev cycle fast; Dockerfiles `COPY common/` then `pip install -e ./common`.
- **`id-ingest/`** — owns identity adapters, `group-sync` worker, and the `identity.events` Redis Stream producer. Mirrors `flow-ingest` layout.
- **`correlator/` extensions** — add identity enrichment + LCD aggregation stages between the P2 `AppResolver` and `Writer` stages.
- **`api/` identity + groups** — two new routers + filter extensions on the Sankey endpoint.
- **`web/` left-column UX** — persist-in-URL toggle, group/user visuals, unknown-strand banner, LCD-fallback badge.
- **`docs/adapters.md` + `docs/identity-model.md`** — operator runbooks and algorithm reference.

---

## Chunk 1: `common/` package + `id-ingest` skeleton

This chunk extracts the shared syslog + ABC + Redis plumbing that P2 landed inside `flow-ingest/` into a dedicated editable-install package so `id-ingest` can reuse it without copy-paste. It then stands up the `id-ingest` service shell (entry point, adapter auto-loader, Dockerfile, Compose wiring) and publishes to the `identity.events` Redis Stream. **No adapter logic lands here** — that is chunks 2 and 3.

Reference skills:
- `@superpowers:test-driven-development`
- `@superpowers:using-git-worktrees`

### Task 1.1: Scaffold `common/` package

**Files:**
- Create: `common/pyproject.toml`
- Create: `common/src/ztna_common/__init__.py`
- Create: `common/tests/__init__.py`

- [ ] **Step 1: Write `common/pyproject.toml`**

```toml
[project]
name = "ztna-common"
version = "0.1.0"
description = "Shared syslog + adapter base for ZTNA flow + id ingest"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "redis>=5.0",
  "loguru>=0.7",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "mypy>=1.10", "ruff>=0.5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ztna_common"]
```

- [ ] **Step 2: Create empty `__init__.py` files**

```python
# common/src/ztna_common/__init__.py
__all__: list[str] = []
```

- [ ] **Step 3: Verify editable install works**

Run: `pip install -e common/[dev]`
Expected: `Successfully installed ztna-common-0.1.0`.

- [ ] **Step 4: Commit**

```bash
git add common/pyproject.toml common/src/ztna_common/__init__.py common/tests/__init__.py
git commit -m "feat(common): scaffold shared ZTNA ingest package"
```

---

### Task 1.2: Move syslog receiver + adapter base from `flow-ingest` to `common`

**Files:**
- Create: `common/src/ztna_common/syslog_receiver.py` (from P2 `flow-ingest/src/flow_ingest/syslog_receiver.py`)
- Create: `common/src/ztna_common/adapter_base.py`
- Create: `common/src/ztna_common/event_types.py`
- Create: `common/src/ztna_common/redis_bus.py`
- Create: `common/src/ztna_common/config.py`
- Create: `common/src/ztna_common/logging_config.py`
- Create: `common/tests/test_syslog_receiver.py`
- Create: `common/tests/test_adapter_base.py`
- Create: `common/tests/test_event_types.py`
- Create: `common/tests/test_redis_bus.py`
- Create: `common/tests/test_config.py`
- Modify: `flow-ingest/src/flow_ingest/*` (replace local copies with `from ztna_common import ...`)
- Modify: `flow-ingest/pyproject.toml` (add `ztna-common @ file://${PROJECT_ROOT}/../common`)

- [ ] **Step 1: Write regression test pinning the shared interface**

Place this in `common/tests/test_adapter_base.py`:

```python
from __future__ import annotations

import inspect

from ztna_common.adapter_base import FlowAdapter, IdentityAdapter
from ztna_common.event_types import FlowEvent, IdentityEvent


def test_flow_adapter_has_required_abstract_methods() -> None:
    methods = {name for name, m in inspect.getmembers(FlowAdapter) if getattr(m, "__isabstractmethod__", False)}
    assert {"run", "healthcheck"} <= methods


def test_identity_adapter_has_required_abstract_methods() -> None:
    methods = {name for name, m in inspect.getmembers(IdentityAdapter) if getattr(m, "__isabstractmethod__", False)}
    assert {"run", "healthcheck"} <= methods


def test_identity_event_required_keys() -> None:
    required = {"ts", "src_ip", "user_upn", "source", "event_type", "confidence", "ttl_seconds"}
    assert required <= set(IdentityEvent.__required_keys__)


def test_flow_event_required_keys() -> None:
    required = {"ts", "src_ip", "dst_ip", "dst_port", "proto", "bytes", "packets", "source"}
    assert required <= set(FlowEvent.__required_keys__)
```

- [ ] **Step 2: Run test, expect ImportError (file does not exist)**

Run: `pytest common/tests/test_adapter_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ztna_common.adapter_base'`.

- [ ] **Step 3: Copy P2's syslog_receiver and ABCs into the new package**

Move the existing files (do not duplicate):

```bash
git mv flow-ingest/src/flow_ingest/syslog_receiver.py common/src/ztna_common/syslog_receiver.py
git mv flow-ingest/src/flow_ingest/adapter_base.py common/src/ztna_common/adapter_base.py
git mv flow-ingest/src/flow_ingest/event_types.py common/src/ztna_common/event_types.py
git mv flow-ingest/src/flow_ingest/redis_bus.py common/src/ztna_common/redis_bus.py
git mv flow-ingest/src/flow_ingest/config.py common/src/ztna_common/config.py
git mv flow-ingest/src/flow_ingest/logging_config.py common/src/ztna_common/logging_config.py
```

Add the `IdentityAdapter` ABC (spec §5.2) to `common/src/ztna_common/adapter_base.py`. Keep `FlowAdapter` untouched:

```python
class IdentityAdapter(ABC):
    """Async identity adapter; emits IdentityEvent per session binding."""

    name: str

    @abstractmethod
    async def run(self) -> AsyncIterator[IdentityEvent]:
        ...

    @abstractmethod
    def healthcheck(self) -> dict[str, object]:
        ...
```

Add `IdentityEvent` TypedDict (spec §5.2) to `common/src/ztna_common/event_types.py`:

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
```

- [ ] **Step 4: Move corresponding flow-ingest tests into `common/tests/`**

```bash
git mv flow-ingest/tests/test_syslog_receiver.py common/tests/test_syslog_receiver.py
git mv flow-ingest/tests/test_redis_bus.py common/tests/test_redis_bus.py
git mv flow-ingest/tests/test_config.py common/tests/test_config.py
```

Add new `common/tests/test_event_types.py` asserting both TypedDicts import cleanly.

- [ ] **Step 5: Rewire flow-ingest imports**

In every `flow-ingest/src/flow_ingest/**/*.py` that imported `flow_ingest.syslog_receiver` / `flow_ingest.adapter_base` / `flow_ingest.event_types` / `flow_ingest.redis_bus` / `flow_ingest.config` / `flow_ingest.logging_config`, rewrite the import to `from ztna_common.syslog_receiver import ...` etc.

- [ ] **Step 6: Update `flow-ingest/pyproject.toml`**

Add dependency block:

```toml
[project]
dependencies = [
  "ztna-common",
  # ... existing P2 deps unchanged
]

[tool.uv.sources]
ztna-common = { path = "../common", editable = true }
```

- [ ] **Step 7: Rerun full suite; expect green**

Run: `pip install -e common/[dev] && pip install -e flow-ingest/[dev] && pytest common/ flow-ingest/`
Expected: all P2 tests pass and new ABC + TypedDict tests pass.

- [ ] **Step 8: Commit**

```bash
git add common/ flow-ingest/pyproject.toml flow-ingest/src flow-ingest/tests
git commit -m "refactor(common): extract syslog+adapter base into ztna-common package"
```

---

### Task 1.3: Scaffold `id-ingest` service

**Files:**
- Create: `id-ingest/pyproject.toml`
- Create: `id-ingest/Dockerfile`
- Create: `id-ingest/src/id_ingest/__init__.py`
- Create: `id-ingest/src/id_ingest/main.py`
- Create: `id-ingest/src/id_ingest/redis_io.py`
- Create: `id-ingest/src/id_ingest/settings.py`
- Create: `id-ingest/src/id_ingest/adapters/__init__.py`
- Create: `id-ingest/tests/conftest.py`
- Create: `id-ingest/tests/test_main.py`

- [ ] **Step 1: Failing test — main auto-loads adapters matching `*_adapter.py`**

Write `id-ingest/tests/test_main.py`:

```python
import pytest

from id_ingest.main import discover_adapters


def test_discover_adapters_picks_up_registered_modules(tmp_path, monkeypatch):
    # Adapter packages are loaded from id_ingest.adapters at import time.
    discovered = discover_adapters()
    names = {cls.name for cls in discovered}
    # In a freshly scaffolded service there are no adapters yet (chunks 2-3 add them).
    assert names == set()


@pytest.mark.asyncio
async def test_main_graceful_shutdown_on_sigterm(monkeypatch):
    from id_ingest import main
    stop = await main.run_once(timeout_s=0.01)
    assert stop is True  # signal loop exits cleanly when no adapters registered
```

- [ ] **Step 2: Run test — expect import failure**

Run: `pytest id-ingest/tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'id_ingest.main'`.

- [ ] **Step 3: Implement `id_ingest.main` minimal auto-loader**

```python
# id-ingest/src/id_ingest/main.py
from __future__ import annotations

import asyncio
import importlib
import pkgutil
import signal
from typing import Sequence

from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.redis_bus import RedisStreamProducer

from id_ingest import adapters as adapters_pkg
from id_ingest.settings import IdIngestSettings


def discover_adapters() -> Sequence[type[IdentityAdapter]]:
    found: list[type[IdentityAdapter]] = []
    for modinfo in pkgutil.iter_modules(adapters_pkg.__path__):
        if not modinfo.name.endswith("_adapter"):
            continue
        mod = importlib.import_module(f"id_ingest.adapters.{modinfo.name}")
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, IdentityAdapter) and obj is not IdentityAdapter:
                found.append(obj)
    return found


async def run_once(timeout_s: float = 1.0) -> bool:
    settings = IdIngestSettings()
    producer = RedisStreamProducer(settings.redis_url, stream="identity.events")
    stop_evt = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop_evt.set)
    loop.add_signal_handler(signal.SIGINT, stop_evt.set)
    try:
        await asyncio.wait_for(stop_evt.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        pass
    finally:
        await producer.aclose()
    return True


async def main() -> None:
    # Wired in later chunks; shell today.
    logger.info("id-ingest starting (no adapters registered yet)")
    await run_once(timeout_s=float("inf"))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Implement `IdIngestSettings`**

```python
# id-ingest/src/id_ingest/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class IdIngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ID_INGEST_", env_file=".env", extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    adapter_config_dir: str = "/etc/flowvis/adapters"
    health_port: int = 8081
    log_level: str = "INFO"
```

- [ ] **Step 5: Implement `redis_io.py` (thin wrapper)**

```python
# id-ingest/src/id_ingest/redis_io.py
from ztna_common.redis_bus import RedisStreamProducer

IDENTITY_STREAM = "identity.events"


def make_producer(redis_url: str) -> RedisStreamProducer:
    return RedisStreamProducer(redis_url, stream=IDENTITY_STREAM)
```

- [ ] **Step 6: Run tests; expect PASS**

Run: `pip install -e id-ingest/[dev] && pytest id-ingest/`
Expected: both tests pass.

- [ ] **Step 7: Commit**

```bash
git add id-ingest/
git commit -m "feat(id-ingest): scaffold service with auto-loader and settings"
```

---

### Task 1.4: Package id-ingest `pyproject.toml` and Dockerfile

**Files:**
- Create: `id-ingest/pyproject.toml`
- Create: `id-ingest/Dockerfile`

- [ ] **Step 1: Write `id-ingest/pyproject.toml`**

```toml
[project]
name = "id-ingest"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "ztna-common",
  "httpx>=0.27",
  "ldap3>=2.9",
  "msal>=1.28",
  "apscheduler>=3.10",
  "intervaltree>=3.1",
  "asyncpg>=0.29",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "mypy>=1.10", "ruff>=0.5"]

[tool.uv.sources]
ztna-common = { path = "../common", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/id_ingest"]
```

- [ ] **Step 2: Write `id-ingest/Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Copy the common package first so editable install points at it.
COPY common/ /app/common/
COPY id-ingest/pyproject.toml /app/id-ingest/pyproject.toml
COPY id-ingest/src /app/id-ingest/src

RUN pip install -e /app/common && pip install -e /app/id-ingest

# Adapter configs mounted at /etc/flowvis/adapters/<name>.yaml
VOLUME ["/etc/flowvis/adapters"]

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8081/health/live').status==200 else 1)"

CMD ["python", "-m", "id_ingest.main"]
```

- [ ] **Step 3: Build image locally**

Run: `docker build -f id-ingest/Dockerfile -t ztna/id-ingest:dev .`
Expected: image builds, no errors.

- [ ] **Step 4: Commit**

```bash
git add id-ingest/pyproject.toml id-ingest/Dockerfile
git commit -m "feat(id-ingest): add pyproject and Dockerfile"
```

---

### Task 1.5: Compose wiring + env placeholders

**Files:**
- Modify: `docker-compose.yml` (add `id-ingest` service)
- Modify: `docker-compose.dev.yml` (hot-reload mount)
- Modify: `.env.example` (add identity source placeholders)

- [ ] **Step 1: Add id-ingest service block to `docker-compose.yml`**

```yaml
  id-ingest:
    build:
      context: .
      dockerfile: id-ingest/Dockerfile
    env_file: .env
    depends_on:
      migrate:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    volumes:
      - ./id-ingest/configs:/etc/flowvis/adapters:ro
    networks: [backend]
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import urllib.request,sys;sys.exit(0 if urllib.request.urlopen(\"http://localhost:8081/health/live\").status==200 else 1)'"]
      interval: 10s
      timeout: 3s
      retries: 5
    labels:
      - traefik.enable=true
      - traefik.docker.network=backend
```

Traefik TCP/UDP routers targeting this service are wired in Chunk 7 (the AD / ISE / ClearPass entrypoints already exist from P1).

- [ ] **Step 2: Add dev override**

```yaml
# docker-compose.dev.yml
services:
  id-ingest:
    build:
      context: .
      dockerfile: id-ingest/Dockerfile
    volumes:
      - ./common/src:/app/common/src
      - ./id-ingest/src:/app/id-ingest/src
    command: ["python", "-m", "id_ingest.main"]
    environment:
      LOG_LEVEL: DEBUG
```

- [ ] **Step 3: Extend `.env.example`**

Append:

```bash
# --- identity sources (P3) ---
# Active Directory (WEF/Winlogbeat forwards Event 4624 as syslog to :516)
AD_LDAP_URL=ldaps://dc.corp.example:636
AD_BIND_DN=CN=ztna-svc,OU=ServiceAccounts,DC=corp,DC=example
AD_BIND_PASSWORD=
AD_BASE_DN=DC=corp,DC=example

# Entra ID (Graph API client-credentials; AuditLog.Read.All)
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=
ENTRA_CORP_CIDRS=10.0.0.0/8,192.168.0.0/16
ENTRA_POLL_INTERVAL_S=60

# Cisco ISE / Aruba ClearPass RADIUS syslog have no credentials (push-based).

# Group sync scheduling
GROUP_SYNC_FULL_CRON=0 2 * * *
```

- [ ] **Step 4: Smoke the compose file**

Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml config >/dev/null`
Expected: no validation errors.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.dev.yml .env.example
git commit -m "feat(id-ingest): compose wiring + identity env placeholders"
```

---

**End of Chunk 1.**
Gate: `pytest common/ flow-ingest/ id-ingest/` green; `docker compose config` valid; no adapter logic yet.

---

## Chunk 2: AD 4624 + Entra sign-in adapters

This chunk delivers the first two identity adapters. Both publish `IdentityEvent` rows to `identity.events`. TDD-first: parse golden fixtures into events, then wire the runtime. Confidence + TTL values track spec §4.2.

Reference skills:
- `@superpowers:test-driven-development`

### Task 2.1: AD 4624 adapter — golden fixtures

**Files:**
- Create: `id-ingest/tests/fixtures/ad_4624/type2_interactive.txt`
- Create: `id-ingest/tests/fixtures/ad_4624/type3_network.txt`
- Create: `id-ingest/tests/fixtures/ad_4624/type10_remote.txt`
- Create: `id-ingest/tests/fixtures/ad_4624/type11_cached.txt`
- Create: `id-ingest/tests/fixtures/ad_4624/malformed.txt`

- [ ] **Step 1: Drop four real-ish WEF/Winlogbeat syslog lines**

Each fixture is a single syslog line shaped like what Winlogbeat emits for Windows Security Event 4624. Use actual Microsoft field names. Example for `type2_interactive.txt`:

```
<13>2026-04-22T12:00:00.000Z DC01 winlogbeat[1234]: {"event_id":4624,"@timestamp":"2026-04-22T12:00:00.000Z","winlog":{"event_data":{"TargetUserName":"alice","TargetDomainName":"CORP","LogonType":"2","IpAddress":"10.0.12.34","WorkstationName":"LAPTOP-ALICE","LogonGuid":"{a1b2c3d4-1111-2222-3333-444455556666}"}}}
```

- `type3_network.txt` — same shape, `LogonType` = `3`, `TargetUserName` = `svc_backup`, `IpAddress` = `10.0.5.17`.
- `type10_remote.txt` — `LogonType` = `10` (RDP), `IpAddress` = `203.0.113.7`.
- `type11_cached.txt` — `LogonType` = `11`, `IpAddress` = `-` (no network address — adapter must skip).
- `malformed.txt` — JSON truncated mid-field; adapter must log a parse error and not raise.

- [ ] **Step 2: Commit fixtures**

```bash
git add id-ingest/tests/fixtures/ad_4624
git commit -m "test(ad_4624): add golden syslog fixtures"
```

---

### Task 2.2: AD 4624 adapter — failing parser test

**Files:**
- Create: `id-ingest/tests/adapters/test_ad_4624_adapter.py`

- [ ] **Step 1: Write test**

```python
from pathlib import Path

import pytest

from id_ingest.adapters.ad_4624_adapter import Ad4624Adapter

FIX = Path(__file__).parent.parent / "fixtures" / "ad_4624"


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ("type2_interactive.txt", {"user_upn": "alice@CORP", "src_ip": "10.0.12.34", "confidence": 90, "ttl_seconds": 28800}),
        ("type3_network.txt",    {"user_upn": "svc_backup@CORP", "src_ip": "10.0.5.17", "confidence": 70, "ttl_seconds": 28800}),
        ("type10_remote.txt",    {"user_upn": "alice@CORP", "src_ip": "203.0.113.7", "confidence": 90, "ttl_seconds": 28800}),
    ],
)
def test_parse_single_line(fixture, expected) -> None:
    adapter = Ad4624Adapter.from_config({})
    line = (FIX / fixture).read_bytes().strip()
    ev = adapter.parse(line)
    assert ev is not None
    for k, v in expected.items():
        assert ev[k] == v
    assert ev["event_type"] == "logon"
    assert ev["source"] == "ad_4624"


def test_parse_skips_missing_ip() -> None:
    adapter = Ad4624Adapter.from_config({})
    line = (FIX / "type11_cached.txt").read_bytes().strip()
    assert adapter.parse(line) is None


def test_parse_malformed_returns_none_without_raising() -> None:
    adapter = Ad4624Adapter.from_config({})
    line = (FIX / "malformed.txt").read_bytes().strip()
    assert adapter.parse(line) is None
```

- [ ] **Step 2: Run, expect import failure**

Run: `pytest id-ingest/tests/adapters/test_ad_4624_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'id_ingest.adapters.ad_4624_adapter'`.

---

### Task 2.3: AD 4624 adapter — minimal implementation

**Files:**
- Create: `id-ingest/src/id_ingest/adapters/ad_4624_adapter.py`

- [ ] **Step 1: Implement**

```python
from __future__ import annotations

import json
from datetime import datetime
from typing import AsyncIterator

from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.event_types import IdentityEvent
from ztna_common.syslog_receiver import SyslogReceiver

# Spec §4.2 confidence table
CONFIDENCE_BY_LOGON_TYPE: dict[str, int] = {"2": 90, "10": 90, "11": 50, "3": 70}
DEFAULT_TTL_S = 8 * 3600
ACCEPTED_LOGON_TYPES = {"2", "3", "10", "11"}


class Ad4624Adapter(IdentityAdapter):
    name = "ad_4624"

    def __init__(self, bind: str = "0.0.0.0", port: int = 516) -> None:
        self._recv = SyslogReceiver(bind=bind, port=port, name="ad_4624")

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> "Ad4624Adapter":
        return cls(
            bind=str(cfg.get("bind", "0.0.0.0")),
            port=int(cfg.get("port", 516)),
        )

    def parse(self, line: bytes) -> IdentityEvent | None:
        try:
            # Winlogbeat syslog frames JSON after the first `: `
            text = line.decode("utf-8", errors="replace")
            payload = text.split(": ", 1)[1] if ": " in text else text
            doc = json.loads(payload)
            if doc.get("event_id") != 4624:
                return None
            data = doc.get("winlog", {}).get("event_data", {})
            logon_type = str(data.get("LogonType", ""))
            ip = data.get("IpAddress")
            if logon_type not in ACCEPTED_LOGON_TYPES or not ip or ip == "-":
                return None
            upn = f"{data['TargetUserName']}@{data.get('TargetDomainName', '')}".rstrip("@")
            ts = datetime.fromisoformat(doc["@timestamp"].replace("Z", "+00:00"))
            return IdentityEvent(
                ts=ts,
                src_ip=ip,
                user_upn=upn,
                source=self.name,
                event_type="logon",
                confidence=CONFIDENCE_BY_LOGON_TYPE.get(logon_type, 50),
                ttl_seconds=DEFAULT_TTL_S,
                mac=None,
                raw_id=data.get("LogonGuid"),
            )
        except Exception as exc:   # noqa: BLE001 — adapters MUST NOT crash the service
            logger.warning("ad_4624 parse error: {}", exc)
            return None

    async def run(self) -> AsyncIterator[IdentityEvent]:
        async for line in self._recv.stream():
            ev = self.parse(line)
            if ev is not None:
                yield ev

    def healthcheck(self) -> dict[str, object]:
        return {"adapter": self.name, "listening": self._recv.is_listening}
```

- [ ] **Step 2: Run parser tests; expect PASS**

Run: `pytest id-ingest/tests/adapters/test_ad_4624_adapter.py -v`
Expected: three parametrized cases + skip + malformed all PASS.

- [ ] **Step 3: Commit**

```bash
git add id-ingest/src/id_ingest/adapters/ad_4624_adapter.py id-ingest/tests/adapters/test_ad_4624_adapter.py
git commit -m "feat(id-ingest): AD 4624 adapter with confidence-by-logon-type"
```

---

### Task 2.4: Entra sign-in adapter — fixtures + mock transport

**Files:**
- Create: `id-ingest/tests/fixtures/entra/signins_page1.json`
- Create: `id-ingest/tests/fixtures/entra/signins_page2.json`
- Create: `id-ingest/tests/fixtures/entra/delta_token.json`
- Create: `id-ingest/tests/fixtures/entra/corp_cidr_hit.json`
- Create: `id-ingest/tests/fixtures/entra/corp_cidr_miss.json`

- [ ] **Step 1: Capture two sign-in pages**

Model them on the real Graph response shape. `signins_page1.json`:

```json
{
  "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#auditLogs/signIns",
  "@odata.nextLink": "https://graph.microsoft.com/v1.0/auditLogs/signIns?$skiptoken=abc",
  "value": [
    {
      "id": "aaa-111",
      "createdDateTime": "2026-04-22T12:05:00Z",
      "userPrincipalName": "alice@corp.example",
      "ipAddress": "10.0.12.34",
      "status": {"errorCode": 0, "additionalDetails": "MFA requirement satisfied by claim in the token"},
      "deviceDetail": {"deviceId": "dev-1"}
    },
    {
      "id": "aaa-112",
      "createdDateTime": "2026-04-22T12:05:03Z",
      "userPrincipalName": "svc@corp.example",
      "ipAddress": "203.0.113.7",
      "status": {"errorCode": 50074, "additionalDetails": "Strong auth required"},
      "deviceDetail": {}
    }
  ]
}
```

- `signins_page2.json` — `@odata.deltaLink` present with success-only events.
- `corp_cidr_hit.json` / `_miss.json` — two single-event payloads used in parametrized confidence tests.

- [ ] **Step 2: Commit fixtures**

```bash
git add id-ingest/tests/fixtures/entra
git commit -m "test(entra): add Graph sign-in golden fixtures"
```

---

### Task 2.5: Entra sign-in adapter — failing test using `httpx.MockTransport`

**Files:**
- Create: `id-ingest/tests/adapters/test_entra_signin_adapter.py`

- [ ] **Step 1: Write test**

```python
import json
from ipaddress import ip_network
from pathlib import Path

import httpx
import pytest

from id_ingest.adapters.entra_signin_adapter import EntraSigninAdapter

FIX = Path(__file__).parent.parent / "fixtures" / "entra"


def _mock_transport() -> httpx.MockTransport:
    pages = [
        json.loads((FIX / "signins_page1.json").read_text()),
        json.loads((FIX / "signins_page2.json").read_text()),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "abc", "expires_in": 3600, "token_type": "Bearer"})
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_adapter_emits_events_for_success_only() -> None:
    adapter = EntraSigninAdapter(
        tenant_id="tid", client_id="cid", client_secret="sec",
        corp_cidrs=[ip_network("10.0.0.0/8")],
        transport=_mock_transport(),
        poll_interval_s=0,
    )
    events = [ev async for ev in adapter.poll_once()]
    # svc@corp.example had errorCode != 0 → must be dropped
    upns = {ev["user_upn"] for ev in events}
    assert "alice@corp.example" in upns
    assert "svc@corp.example" not in upns


@pytest.mark.asyncio
async def test_confidence_by_corp_cidr_membership() -> None:
    adapter = EntraSigninAdapter(
        tenant_id="tid", client_id="cid", client_secret="sec",
        corp_cidrs=[ip_network("10.0.0.0/8")],
        transport=_mock_transport(),
        poll_interval_s=0,
    )
    events = [ev async for ev in adapter.poll_once()]
    by_upn = {ev["user_upn"]: ev for ev in events}
    assert by_upn["alice@corp.example"]["confidence"] == 80
    # Any event whose IP is outside the corp_cidrs must land at 40.
    outside = [ev for ev in events if ev["confidence"] == 40]
    assert any(outside)
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

Run: `pytest id-ingest/tests/adapters/test_entra_signin_adapter.py -v`
Expected: FAIL.

---

### Task 2.6: Entra sign-in adapter — minimal implementation

**Files:**
- Create: `id-ingest/src/id_ingest/adapters/entra_signin_adapter.py`

- [ ] **Step 1: Implement**

```python
from __future__ import annotations

import asyncio
from datetime import datetime
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import AsyncIterator

import httpx
from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.event_types import IdentityEvent

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTH_BASE = "https://login.microsoftonline.com"
CONF_IN = 80
CONF_OUT = 40
TTL_S = 3600


class EntraSigninAdapter(IdentityAdapter):
    name = "entra_signin"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        corp_cidrs: list[IPv4Network | IPv6Network],
        *,
        transport: httpx.BaseTransport | None = None,
        poll_interval_s: int = 60,
    ) -> None:
        self._tid = tenant_id
        self._cid = client_id
        self._sec = client_secret
        self._cidrs = corp_cidrs
        self._poll = poll_interval_s
        self._client = httpx.AsyncClient(transport=transport, timeout=30.0)
        self._delta_link: str | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> "EntraSigninAdapter":
        cidrs = [ip_network(c) for c in cfg.get("corp_cidrs", [])]  # type: ignore[arg-type]
        return cls(
            tenant_id=str(cfg["tenant_id"]),
            client_id=str(cfg["client_id"]),
            client_secret=str(cfg["client_secret"]),
            corp_cidrs=cidrs,
            poll_interval_s=int(cfg.get("poll_interval_s", 60)),
        )

    async def _token(self) -> str:
        resp = await self._client.post(
            f"{AUTH_BASE}/{self._tid}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._cid,
                "client_secret": self._sec,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _confidence(self, ip: str) -> int:
        try:
            addr = ip_address(ip)
        except ValueError:
            return CONF_OUT
        return CONF_IN if any(addr in c for c in self._cidrs) else CONF_OUT

    async def poll_once(self) -> AsyncIterator[IdentityEvent]:
        token = await self._token()
        url = self._delta_link or f"{GRAPH_BASE}/auditLogs/signIns?$filter=status/errorCode eq 0"
        while url:
            r = await self._client.get(url, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            body = r.json()
            for item in body.get("value", []):
                if item.get("status", {}).get("errorCode") != 0:
                    continue
                ip = item.get("ipAddress")
                upn = item.get("userPrincipalName")
                if not ip or not upn:
                    continue
                ts = datetime.fromisoformat(item["createdDateTime"].replace("Z", "+00:00"))
                yield IdentityEvent(
                    ts=ts,
                    src_ip=ip,
                    user_upn=upn,
                    source=self.name,
                    event_type="logon",
                    confidence=self._confidence(ip),
                    ttl_seconds=TTL_S,
                    mac=None,
                    raw_id=item.get("id"),
                )
            url = body.get("@odata.nextLink")
            if not url and body.get("@odata.deltaLink"):
                self._delta_link = body["@odata.deltaLink"]

    async def run(self) -> AsyncIterator[IdentityEvent]:
        while True:
            try:
                async for ev in self.poll_once():
                    yield ev
            except Exception as exc:   # noqa: BLE001
                logger.warning("entra_signin poll error: {}", exc)
            await asyncio.sleep(self._poll)

    def healthcheck(self) -> dict[str, object]:
        return {"adapter": self.name, "delta_link_seen": bool(self._delta_link)}
```

- [ ] **Step 2: Run all Entra tests**

Run: `pytest id-ingest/tests/adapters/test_entra_signin_adapter.py -v`
Expected: both tests PASS.

- [ ] **Step 3: Commit**

```bash
git add id-ingest/src/id_ingest/adapters/entra_signin_adapter.py id-ingest/tests/adapters/test_entra_signin_adapter.py
git commit -m "feat(id-ingest): Entra sign-in adapter with delta poll + corp_cidrs confidence"
```

---

**End of Chunk 2.**
Gate: `pytest id-ingest/tests/adapters/` green for AD + Entra; both adapters auto-discover via `discover_adapters()`; neither raises on malformed input.

---

<!-- CHUNK-3-PLACEHOLDER -->

---

<!-- CHUNK-4-PLACEHOLDER -->

---

<!-- CHUNK-5-PLACEHOLDER -->

---

<!-- CHUNK-6-PLACEHOLDER -->

---

<!-- CHUNK-7-PLACEHOLDER -->
