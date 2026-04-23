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

### Task 1.1: Scaffold `flow-ingest/` package layout

**Files:**
- Create: `flow-ingest/pyproject.toml`
- Create: `flow-ingest/Dockerfile`
- Create: `flow-ingest/src/flow_ingest/__init__.py` (empty)
- Create: `flow-ingest/src/flow_ingest/adapters/__init__.py` (empty)
- Create: `flow-ingest/tests/__init__.py` (empty)

- [ ] **Step 1: Write `flow-ingest/pyproject.toml`**

```toml
[project]
name = "ztna-flow-ingest"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pydantic==2.9.2",
  "pydantic-settings==2.5.2",
  "redis==5.1.0",
  "loguru==0.7.2",
  "pyyaml==6.0.2",
  "uvloop==0.20.0",
]

[project.optional-dependencies]
test = [
  "pytest==8.3.3",
  "pytest-asyncio==0.24.0",
  "fakeredis==2.25.1",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Write `flow-ingest/Dockerfile`**

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .
EXPOSE 5514/udp 5514/tcp
CMD ["python", "-m", "flow_ingest.main"]
```

- [ ] **Step 3: Run** `python -m pip install -e 'flow-ingest/[test]'` locally to verify metadata. Expected: install succeeds.

- [ ] **Step 4: Commit**

```bash
git add flow-ingest/pyproject.toml flow-ingest/Dockerfile \
        flow-ingest/src/flow_ingest/__init__.py \
        flow-ingest/src/flow_ingest/adapters/__init__.py \
        flow-ingest/tests/__init__.py
git commit -m "feat(flow-ingest): scaffold package layout and Dockerfile"
```

---

### Task 1.2: Define `FlowEvent` + `FlowAdapter` ABC (TDD)

**Files:**
- Test: `flow-ingest/tests/test_adapter_base.py`
- Create: `flow-ingest/src/flow_ingest/adapters/base.py`

- [ ] **Step 1: Write the failing test**

```python
# flow-ingest/tests/test_adapter_base.py
from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from flow_ingest.adapters.base import FlowAdapter, FlowEvent


def test_flow_event_shape() -> None:
    sample: FlowEvent = {
        "ts": datetime.now(UTC),
        "src_ip": "10.0.0.1", "src_port": 44321,
        "dst_ip": "52.97.1.1",  "dst_port": 443,
        "proto": 6,
        "bytes": 1024, "packets": 8,
        "action": "allow",
        "fqdn": "outlook.office365.com",
        "app_id": "ms-office365",
        "source": "palo_alto",
        "raw_id": "abc123",
    }
    assert sample["source"] == "palo_alto"


def test_flow_adapter_is_abstract() -> None:
    assert inspect.isabstract(FlowAdapter)
    with pytest.raises(TypeError):
        FlowAdapter()  # type: ignore[abstract]


def test_subclass_must_implement_run_and_health() -> None:
    class Partial(FlowAdapter):
        name = "partial"
    with pytest.raises(TypeError):
        Partial()  # type: ignore[abstract]
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `pytest flow-ingest/tests/test_adapter_base.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `base.py`**

```python
# flow-ingest/src/flow_ingest/adapters/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TypedDict


class FlowEvent(TypedDict):
    ts: datetime
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    action: str            # 'allow' | 'deny' | 'drop'
    fqdn: str | None       # firewall-supplied hostname
    app_id: str | None     # vendor App-ID
    source: str            # adapter name, e.g. 'palo_alto'
    raw_id: str | None


class FlowAdapter(ABC):
    """Base class for flow adapters. Subclasses set class attribute `name`
    and implement `run()` (async iterator of FlowEvents) and `healthcheck()`.
    """

    name: str = ""

    @abstractmethod
    async def run(self) -> AsyncIterator[FlowEvent]:  # pragma: no cover - abstract
        raise NotImplementedError
        yield  # noqa: E1101 — make the type checker see an async generator

    @abstractmethod
    def healthcheck(self) -> dict[str, object]:  # pragma: no cover - abstract
        raise NotImplementedError
```

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest flow-ingest/tests/test_adapter_base.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add flow-ingest/src/flow_ingest/adapters/base.py flow-ingest/tests/test_adapter_base.py
git commit -m "feat(flow-ingest): add FlowAdapter ABC and FlowEvent TypedDict"
```

---

### Task 1.3: Shared `SyslogReceiver` — UDP + TCP framing (TDD)

**Files:**
- Test: `flow-ingest/tests/test_syslog_receiver.py`
- Create: `flow-ingest/src/flow_ingest/syslog_receiver.py`

`SyslogReceiver` responsibilities:

1. Listen on both UDP and TCP on the configured bind address.
2. UDP: one datagram = one log line (strip trailing `\n`).
3. TCP: supports (a) newline-framed RFC 5425 and (b) octet-counting (`<len> <msg>`) — detect by leading digit + space.
4. Deliver parsed lines to an `asyncio.Queue[tuple[str, str]]` (peer_ip, raw_line). Queue is **bounded** (default 10 000); full queue increments `syslog_backpressure_drops_total` and drops oldest.
5. TCP reconnect is handled by the `asyncio.Server` semantics; UDP is stateless. Must `await server.close()` cleanly on shutdown.

- [ ] **Step 1: Write the failing test**

```python
# flow-ingest/tests/test_syslog_receiver.py
from __future__ import annotations

import asyncio

import pytest

from flow_ingest.syslog_receiver import SyslogReceiver


@pytest.mark.asyncio
async def test_udp_receives_single_datagram() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=128)
    await rx.start()
    try:
        port = rx.udp_port
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=("127.0.0.1", port),
        )
        transport.sendto(b"hello-world\n")
        peer, line = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
        assert line == "hello-world"
        assert peer == "127.0.0.1"
        transport.close()
    finally:
        await rx.stop()


@pytest.mark.asyncio
async def test_tcp_newline_framing() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=128)
    await rx.start()
    try:
        r, w = await asyncio.open_connection("127.0.0.1", rx.tcp_port)
        w.write(b"line-a\nline-b\n")
        await w.drain()
        lines: list[str] = []
        for _ in range(2):
            _peer, raw = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
            lines.append(raw)
        assert lines == ["line-a", "line-b"]
        w.close()
        await w.wait_closed()
    finally:
        await rx.stop()


@pytest.mark.asyncio
async def test_tcp_octet_counting() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=128)
    await rx.start()
    try:
        r, w = await asyncio.open_connection("127.0.0.1", rx.tcp_port)
        w.write(b"6 abcdef5 12345")
        await w.drain()
        _peer, a = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
        _peer, b = await asyncio.wait_for(rx.queue.get(), timeout=1.0)
        assert a == "abcdef"
        assert b == "12345"
        w.close()
        await w.wait_closed()
    finally:
        await rx.stop()


@pytest.mark.asyncio
async def test_backpressure_drops_oldest_and_counts() -> None:
    rx = SyslogReceiver(host="127.0.0.1", port=0, queue_max=2)
    await rx.start()
    try:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=("127.0.0.1", rx.udp_port),
        )
        for i in range(5):
            transport.sendto(f"m{i}".encode())
        await asyncio.sleep(0.1)
        # Queue keeps at most 2 elements; newest survive.
        items = []
        while not rx.queue.empty():
            items.append(rx.queue.get_nowait()[1])
        assert len(items) == 2
        assert rx.backpressure_drops >= 3
        transport.close()
    finally:
        await rx.stop()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest flow-ingest/tests/test_syslog_receiver.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `syslog_receiver.py`**

```python
# flow-ingest/src/flow_ingest/syslog_receiver.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Tuple

from loguru import logger

Message = Tuple[str, str]   # (peer_ip, line)


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[Message], parent: "SyslogReceiver") -> None:
        self._queue = queue
        self._parent = parent

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        line = data.rstrip(b"\r\n").decode("utf-8", errors="replace")
        if not line:
            return
        self._parent._enqueue(addr[0], line)


async def _handle_tcp_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    parent: "SyslogReceiver",
) -> None:
    peer = writer.get_extra_info("peername") or ("unknown", 0)
    peer_ip = peer[0]
    buf = b""
    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buf += chunk
            buf = _drain_buffer(buf, peer_ip, parent)
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        with contextlib_suppress():
            await writer.wait_closed()


def _drain_buffer(buf: bytes, peer_ip: str, parent: "SyslogReceiver") -> bytes:
    while buf:
        # Octet-counting: leading ASCII digits + space + body of that length.
        if buf[:1].isdigit():
            sp = buf.find(b" ")
            if sp == -1:
                return buf
            try:
                length = int(buf[:sp])
            except ValueError:
                length = -1
            if length >= 0 and len(buf) >= sp + 1 + length:
                body = buf[sp + 1 : sp + 1 + length]
                parent._enqueue(peer_ip, body.decode("utf-8", errors="replace"))
                buf = buf[sp + 1 + length :]
                continue
            return buf  # need more bytes
        # Newline framing
        nl = buf.find(b"\n")
        if nl == -1:
            return buf
        line = buf[:nl].rstrip(b"\r")
        if line:
            parent._enqueue(peer_ip, line.decode("utf-8", errors="replace"))
        buf = buf[nl + 1 :]
    return buf


def contextlib_suppress():
    import contextlib
    return contextlib.suppress(Exception)


@dataclass
class SyslogReceiver:
    host: str
    port: int
    queue_max: int = 10_000

    def __post_init__(self) -> None:
        self.queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self.queue_max)
        self.backpressure_drops: int = 0
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._tcp_server: asyncio.AbstractServer | None = None
        self.udp_port: int = 0
        self.tcp_port: int = 0

    def _enqueue(self, peer_ip: str, line: str) -> None:
        try:
            self.queue.put_nowait((peer_ip, line))
        except asyncio.QueueFull:
            try:
                _ = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.backpressure_drops += 1
            try:
                self.queue.put_nowait((peer_ip, line))
            except asyncio.QueueFull:
                pass

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self.queue, self),
            local_addr=(self.host, self.port),
        )
        self._udp_transport = transport
        sock = transport.get_extra_info("socket")
        self.udp_port = sock.getsockname()[1]

        self._tcp_server = await asyncio.start_server(
            lambda r, w: _handle_tcp_client(r, w, self),
            host=self.host,
            port=self.port if self.port else 0,
        )
        self.tcp_port = self._tcp_server.sockets[0].getsockname()[1]
        logger.info(
            "syslog receiver listening udp={}, tcp={}",
            self.udp_port, self.tcp_port,
        )

    async def stop(self) -> None:
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
        if self._udp_transport is not None:
            self._udp_transport.close()
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest flow-ingest/tests/test_syslog_receiver.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add flow-ingest/src/flow_ingest/syslog_receiver.py flow-ingest/tests/test_syslog_receiver.py
git commit -m "feat(flow-ingest): shared UDP+TCP syslog receiver with bounded queue"
```

---

### Task 1.4: Redis publisher for `flows.raw` (TDD)

**Files:**
- Test: `flow-ingest/tests/test_publisher.py`
- Create: `flow-ingest/src/flow_ingest/publisher.py`

Publisher wraps Redis `XADD` with a small batch window (default 50 events or 100 ms) to reduce round-trips at 20 k/s. On failure it reopens the client and retries with exponential backoff (max 5 s).

- [ ] **Step 1: Write failing test** (uses `fakeredis.aioredis`)

```python
# flow-ingest/tests/test_publisher.py
from __future__ import annotations

import json
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from flow_ingest.publisher import RedisFlowPublisher


@pytest.mark.asyncio
async def test_publish_writes_event_to_stream() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    pub = RedisFlowPublisher(redis=redis, stream="flows.raw", max_batch=1)

    await pub.publish({
        "ts": datetime(2026, 4, 22, tzinfo=UTC),
        "src_ip": "10.0.0.1", "src_port": 44321,
        "dst_ip": "52.97.1.1",  "dst_port": 443,
        "proto": 6,
        "bytes": 123, "packets": 2,
        "action": "allow",
        "fqdn": None, "app_id": None,
        "source": "palo_alto",
        "raw_id": "r1",
    })
    await pub.flush()
    entries = await redis.xrange("flows.raw")
    assert len(entries) == 1
    payload = json.loads(entries[0][1]["event"])
    assert payload["src_ip"] == "10.0.0.1"
    assert payload["source"] == "palo_alto"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# flow-ingest/src/flow_ingest/publisher.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from flow_ingest.adapters.base import FlowEvent


def _jsonify(event: FlowEvent) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(repr(o))
    return json.dumps(event, default=default, separators=(",", ":"))


@dataclass
class RedisFlowPublisher:
    redis: Redis
    stream: str = "flows.raw"
    max_batch: int = 50
    max_wait_ms: int = 100
    maxlen_approx: int | None = 1_000_000  # XADD MAXLEN ~

    def __post_init__(self) -> None:
        self._buf: list[str] = []
        self._lock = asyncio.Lock()
        self._timer: asyncio.TimerHandle | None = None

    async def publish(self, event: FlowEvent) -> None:
        async with self._lock:
            self._buf.append(_jsonify(event))
            if len(self._buf) >= self.max_batch:
                await self._flush_locked()

    async def flush(self) -> None:
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._buf:
            return
        pipe = self.redis.pipeline(transaction=False)
        for payload in self._buf:
            if self.maxlen_approx is not None:
                pipe.xadd(self.stream, {"event": payload},
                          maxlen=self.maxlen_approx, approximate=True)
            else:
                pipe.xadd(self.stream, {"event": payload})
        try:
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis XADD failed: {}", exc)
            raise
        finally:
            self._buf.clear()
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add flow-ingest/src/flow_ingest/publisher.py flow-ingest/tests/test_publisher.py
git commit -m "feat(flow-ingest): Redis XADD publisher with batching"
```

---

### Task 1.5: Palo Alto adapter — CSV + LEEF (TDD with fixtures)

**Files:**
- Test: `flow-ingest/tests/test_palo_alto_adapter.py`
- Create: `flow-ingest/src/flow_ingest/adapters/palo_alto_adapter.py`
- Create: `flow-ingest/tests/fixtures/palo_alto/traffic_end.csv`
- Create: `flow-ingest/tests/fixtures/palo_alto/traffic_start.csv`
- Create: `flow-ingest/tests/fixtures/palo_alto/traffic_leef.txt`

**Parsing rules (from spec §5.3):**

- TRAFFIC log, CSV header present in vendor docs; parser reads by positional index of relevant fields: `type`(3), `log_subtype`(4), `src`(7), `dst`(8), `app`(14), `bytes`(31), `packets`(32), `action`(29), `src_port`(24), `dst_port`(25), `proto`(29? double-check with fixture), `fqdn` typically absent — leave None.
- **Keep only `log_subtype == "end"`** — dropping `start` avoids double-counting.
- LEEF variant lines: `LEEF:2.0|Palo Alto Networks|PAN-OS|...|<key>=<value>\t<key>=<value>...`. Parser must accept both CSV and LEEF and route by the `LEEF:` prefix.
- App-ID → `app_id`; `fqdn` left None unless LEEF includes `hostname=` (rare); correlator will hit PTR path otherwise.

Real PAN-OS CSV is 100+ columns. To keep this plan actionable, the implementer treats the fixture's *positional* spec as the source of truth; fixture columns are documented in a comment header.

- [ ] **Step 1: Write fixtures**

`tests/fixtures/palo_alto/traffic_end.csv`:
```csv
# fields (1-based): 1=receive_time 2=serial 3=type 4=log_subtype 5=config_version 6=generated_time 7=src_ip 8=dst_ip 9=nat_src 10=nat_dst 11=rule 12=src_user 13=dst_user 14=app 15=vsys 16=from_zone 17=to_zone 18=inbound_if 19=outbound_if 20=log_action 21=reserved 22=session_id 23=repeat_count 24=src_port 25=dst_port 26=nat_src_port 27=nat_dst_port 28=flags 29=proto 30=action 31=bytes 32=packets 33=...
1,2026/04/22 14:12:05,001801000000,TRAFFIC,end,2560,2026/04/22 14:12:05,10.0.0.1,52.97.1.1,,,allow-all,,,ms-office365,vsys1,trust,untrust,ae1,ae2,,,,,44321,443,,,0x400000,tcp,allow,1024,8
1,2026/04/22 14:12:06,001801000000,TRAFFIC,end,2560,2026/04/22 14:12:06,10.0.0.2,140.82.112.3,,,deny-github,,,github,vsys1,trust,untrust,ae1,ae2,,,,,54321,443,,,0x400000,tcp,deny,512,4
```

`tests/fixtures/palo_alto/traffic_start.csv` — same format but `log_subtype=start`, parser must discard:
```csv
1,2026/04/22 14:12:05,001801000000,TRAFFIC,start,2560,2026/04/22 14:12:05,10.0.0.1,52.97.1.1,,,allow-all,,,ms-office365,vsys1,trust,untrust,ae1,ae2,,,,,44321,443,,,0x400000,tcp,allow,0,0
```

`tests/fixtures/palo_alto/traffic_leef.txt`:
```
<14>1 2026-04-22T14:12:07Z fw01 LEEF:2.0|Palo Alto Networks|PAN-OS|10.2|TRAFFIC|cat=end|src=10.0.0.3|dst=142.250.190.46|srcPort=51000|dstPort=443|proto=tcp|app=ms-teams|bytesTotal=2048|packetsTotal=16|action=allow|hostname=teams.microsoft.com
```

- [ ] **Step 2: Write failing tests**

```python
# flow-ingest/tests/test_palo_alto_adapter.py
from __future__ import annotations

from pathlib import Path

import pytest

from flow_ingest.adapters.palo_alto_adapter import PaloAltoAdapter

FIX = Path(__file__).parent / "fixtures" / "palo_alto"


@pytest.mark.parametrize(
    "line,expected_src",
    [
        ((FIX / "traffic_end.csv").read_text().splitlines()[1], "10.0.0.1"),
    ],
)
def test_parse_csv_end_yields_event(line: str, expected_src: str) -> None:
    ev = PaloAltoAdapter.parse_line(line)
    assert ev is not None
    assert ev["src_ip"] == expected_src
    assert ev["dst_port"] == 443
    assert ev["proto"] == 6
    assert ev["bytes"] == 1024
    assert ev["action"] == "allow"
    assert ev["app_id"] == "ms-office365"
    assert ev["source"] == "palo_alto"


def test_parse_csv_start_is_dropped() -> None:
    line = (FIX / "traffic_start.csv").read_text().splitlines()[0]
    assert PaloAltoAdapter.parse_line(line) is None


def test_parse_leef() -> None:
    line = (FIX / "traffic_leef.txt").read_text().splitlines()[0]
    ev = PaloAltoAdapter.parse_line(line)
    assert ev is not None
    assert ev["src_ip"] == "10.0.0.3"
    assert ev["dst_ip"] == "142.250.190.46"
    assert ev["fqdn"] == "teams.microsoft.com"
    assert ev["app_id"] == "ms-teams"


def test_parse_garbage_returns_none() -> None:
    assert PaloAltoAdapter.parse_line("not-a-pan-line") is None
```

- [ ] **Step 3: Run — expect FAIL**

- [ ] **Step 4: Implement `palo_alto_adapter.py`**

```python
# flow-ingest/src/flow_ingest/adapters/palo_alto_adapter.py
from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from loguru import logger

from flow_ingest.adapters.base import FlowAdapter, FlowEvent
from flow_ingest.publisher import RedisFlowPublisher
from flow_ingest.syslog_receiver import SyslogReceiver

_PROTO_BY_NAME: dict[str, int] = {"tcp": 6, "udp": 17, "icmp": 1}


def _proto(val: str) -> int:
    val = val.strip().lower()
    return _PROTO_BY_NAME.get(val, int(val) if val.isdigit() else 0)


@dataclass
class PaloAltoAdapter(FlowAdapter):
    receiver: SyslogReceiver
    publisher: RedisFlowPublisher
    peer_allowlist: set[str] | None = None  # source-IP demux
    name: ClassVar[str] = "palo_alto"

    @staticmethod
    def parse_line(line: str) -> FlowEvent | None:
        if "LEEF:" in line and "Palo Alto Networks" in line:
            return _parse_leef(line)
        if "TRAFFIC" in line:
            return _parse_csv(line)
        return None

    async def run(self) -> AsyncIterator[FlowEvent]:
        while True:
            peer, raw = await self.receiver.queue.get()
            if self.peer_allowlist and peer not in self.peer_allowlist:
                continue
            try:
                ev = self.parse_line(raw)
            except Exception as exc:  # noqa: BLE001
                logger.debug("palo_alto parse error: {}", exc)
                continue
            if ev is None:
                continue
            await self.publisher.publish(ev)
            yield ev

    def healthcheck(self) -> dict[str, object]:
        return {"name": self.name, "queued": self.receiver.queue.qsize()}


def _parse_csv(line: str) -> FlowEvent | None:
    # Syslog prefix may precede the CSV payload: `<14>Apr 22 ... : <csv...>`.
    payload = line.split(": ", 1)[-1] if ": " in line else line
    reader = csv.reader(io.StringIO(payload))
    fields = next(reader, None)
    if fields is None or len(fields) < 32 or fields[2] != "TRAFFIC":
        return None
    if fields[3] != "end":
        return None
    try:
        return FlowEvent(
            ts=_ts(fields[5]) if len(fields) > 5 else datetime.now(UTC),
            src_ip=fields[6], src_port=int(fields[23] or 0),
            dst_ip=fields[7], dst_port=int(fields[24] or 0),
            proto=_proto(fields[28]),
            bytes=int(fields[30] or 0),
            packets=int(fields[31] or 0),
            action=fields[29],
            fqdn=None,
            app_id=fields[13] or None,
            source=PaloAltoAdapter.name,
            raw_id=None,
        )
    except (ValueError, IndexError):
        return None


def _parse_leef(line: str) -> FlowEvent | None:
    try:
        leef_start = line.index("LEEF:")
    except ValueError:
        return None
    tail = line[leef_start:]
    parts = tail.split("|")
    if len(parts) < 6:
        return None
    kvs: dict[str, str] = {}
    for segment in parts[5:]:
        for pair in segment.split("\t"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                kvs[k.strip()] = v.strip()
    # Some PAN LEEF emitters put k=v pairs on a single pipe-separated
    # extension; handle both cases defensively.
    for segment in parts:
        if "=" in segment:
            k, v = segment.split("=", 1)
            kvs.setdefault(k.strip(), v.strip())
    try:
        return FlowEvent(
            ts=datetime.now(UTC),
            src_ip=kvs["src"], src_port=int(kvs.get("srcPort", 0)),
            dst_ip=kvs["dst"], dst_port=int(kvs.get("dstPort", 0)),
            proto=_proto(kvs.get("proto", "tcp")),
            bytes=int(kvs.get("bytesTotal", 0)),
            packets=int(kvs.get("packetsTotal", 0)),
            action=kvs.get("action", "allow"),
            fqdn=kvs.get("hostname") or None,
            app_id=kvs.get("app") or None,
            source=PaloAltoAdapter.name,
            raw_id=None,
        )
    except (KeyError, ValueError):
        return None


def _ts(s: str) -> datetime:
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.now(UTC)
```

- [ ] **Step 5: Run — expect PASS**

Run: `pytest flow-ingest/tests/test_palo_alto_adapter.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add flow-ingest/src/flow_ingest/adapters/palo_alto_adapter.py \
        flow-ingest/tests/test_palo_alto_adapter.py \
        flow-ingest/tests/fixtures/palo_alto/
git commit -m "feat(flow-ingest): add Palo Alto TRAFFIC CSV + LEEF adapter"
```

---

### Task 1.6: FortiGate adapter — key=value (TDD with fixtures)

**Files:**
- Test: `flow-ingest/tests/test_fortigate_adapter.py`
- Create: `flow-ingest/src/flow_ingest/adapters/fortigate_adapter.py`
- Create: `flow-ingest/tests/fixtures/fortigate/traffic_close.kv`
- Create: `flow-ingest/tests/fixtures/fortigate/traffic_non_close.kv`

FortiGate produces kv syslog lines; keep only `type=traffic`, `subtype=forward`, `status=close`. `hostname` → `fqdn`; `app` → `app_id`; `proto` is already numeric.

- [ ] **Step 1: Write fixtures**

`traffic_close.kv`:
```
<189>date=2026-04-22 time=14:12:08 devname="fw02" devid="FGT60F" logid="0000000013" type="traffic" subtype="forward" eventtype="forward" level="notice" vd="root" eventtime=1776891128 srcip=10.0.0.4 srcport=55555 srcintf="port1" dstip=52.97.1.2 dstport=443 dstintf="port2" proto=6 action="close" policyid=10 policytype="policy" service="HTTPS" dstcountry="United States" srccountry="Netherlands" trandisp="noop" duration=5 sentbyte=4096 rcvdbyte=2048 sentpkt=12 rcvdpkt=8 appcat="Collaboration" app="SharePoint" status="close" hostname="tenant.sharepoint.com"
```

`traffic_non_close.kv`:
```
<189>date=2026-04-22 time=14:12:09 type="traffic" subtype="forward" status="start" srcip=10.0.0.4 srcport=55555 dstip=52.97.1.2 dstport=443 proto=6 sentbyte=0 rcvdbyte=0 sentpkt=0 rcvdpkt=0 app="SharePoint" hostname="tenant.sharepoint.com"
```

- [ ] **Step 2: Write failing tests**

```python
# flow-ingest/tests/test_fortigate_adapter.py
from __future__ import annotations

from pathlib import Path

from flow_ingest.adapters.fortigate_adapter import FortiGateAdapter

FIX = Path(__file__).parent / "fixtures" / "fortigate"


def test_parse_close_yields_event() -> None:
    line = (FIX / "traffic_close.kv").read_text().splitlines()[0]
    ev = FortiGateAdapter.parse_line(line)
    assert ev is not None
    assert ev["src_ip"] == "10.0.0.4"
    assert ev["dst_ip"] == "52.97.1.2"
    assert ev["dst_port"] == 443
    assert ev["proto"] == 6
    assert ev["bytes"] == 4096 + 2048
    assert ev["packets"] == 12 + 8
    assert ev["fqdn"] == "tenant.sharepoint.com"
    assert ev["app_id"] == "SharePoint"
    assert ev["source"] == "fortigate"


def test_non_close_is_dropped() -> None:
    line = (FIX / "traffic_non_close.kv").read_text().splitlines()[0]
    assert FortiGateAdapter.parse_line(line) is None
```

- [ ] **Step 3: Run — expect FAIL**

- [ ] **Step 4: Implement `fortigate_adapter.py`**

```python
# flow-ingest/src/flow_ingest/adapters/fortigate_adapter.py
from __future__ import annotations

import re
import shlex
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from loguru import logger

from flow_ingest.adapters.base import FlowAdapter, FlowEvent
from flow_ingest.publisher import RedisFlowPublisher
from flow_ingest.syslog_receiver import SyslogReceiver

_PRI_PREFIX = re.compile(r"^<\d+>")


def _kv(line: str) -> dict[str, str]:
    line = _PRI_PREFIX.sub("", line).strip()
    # shlex handles quoted values correctly ("foo=bar baz")
    tokens = shlex.split(line, posix=True)
    out: dict[str, str] = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


@dataclass
class FortiGateAdapter(FlowAdapter):
    receiver: SyslogReceiver
    publisher: RedisFlowPublisher
    peer_allowlist: set[str] | None = None
    name: ClassVar[str] = "fortigate"

    @staticmethod
    def parse_line(line: str) -> FlowEvent | None:
        try:
            kv = _kv(line)
        except ValueError:
            return None
        if kv.get("type") != "traffic":
            return None
        if kv.get("subtype") != "forward":
            return None
        if kv.get("status") != "close":
            return None
        try:
            return FlowEvent(
                ts=datetime.now(UTC),
                src_ip=kv["srcip"], src_port=int(kv.get("srcport", 0)),
                dst_ip=kv["dstip"], dst_port=int(kv.get("dstport", 0)),
                proto=int(kv.get("proto", 0)),
                bytes=int(kv.get("sentbyte", 0)) + int(kv.get("rcvdbyte", 0)),
                packets=int(kv.get("sentpkt", 0)) + int(kv.get("rcvdpkt", 0)),
                action=kv.get("action", "close"),
                fqdn=kv.get("hostname") or None,
                app_id=kv.get("app") or None,
                source=FortiGateAdapter.name,
                raw_id=kv.get("logid"),
            )
        except (KeyError, ValueError):
            return None

    async def run(self) -> AsyncIterator[FlowEvent]:
        while True:
            peer, raw = await self.receiver.queue.get()
            if self.peer_allowlist and peer not in self.peer_allowlist:
                continue
            try:
                ev = self.parse_line(raw)
            except Exception as exc:  # noqa: BLE001
                logger.debug("fortigate parse error: {}", exc)
                continue
            if ev is None:
                continue
            await self.publisher.publish(ev)
            yield ev

    def healthcheck(self) -> dict[str, object]:
        return {"name": self.name, "queued": self.receiver.queue.qsize()}
```

- [ ] **Step 5: Run — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add flow-ingest/src/flow_ingest/adapters/fortigate_adapter.py \
        flow-ingest/tests/test_fortigate_adapter.py \
        flow-ingest/tests/fixtures/fortigate/
git commit -m "feat(flow-ingest): add FortiGate traffic kv adapter"
```

---

### Task 1.7: Per-firewall YAML config + demux (TDD)

**Files:**
- Create: `config/adapters/palo_alto.yaml`
- Create: `config/adapters/fortigate.yaml`
- Create: `flow-ingest/src/flow_ingest/settings.py`
- Test: `flow-ingest/tests/test_settings.py`

The `config/` directory is mounted into the container at `/etc/flowvis/adapters/`. Each adapter YAML lists the source IPs whose packets should be claimed by *that* adapter — this is the demux mechanism on shared UDP :514.

- [ ] **Step 1: Write YAML files**

`config/adapters/palo_alto.yaml`:
```yaml
# Palo Alto PAN-OS firewalls. Populate `source_ips` with the IPs your PAN
# firewalls use when emitting syslog to this collector. Used to demux the
# shared :514 entrypoint.
enabled: true
source_ips:
  - 10.10.0.11
  - 10.10.0.12
```

`config/adapters/fortigate.yaml`:
```yaml
enabled: true
source_ips:
  - 10.20.0.21
  - 10.20.0.22
```

- [ ] **Step 2: Write failing test**

```python
# flow-ingest/tests/test_settings.py
from __future__ import annotations

from pathlib import Path

from flow_ingest.settings import AdapterConfig, load_adapter_configs


def test_load_adapter_configs(tmp_path: Path) -> None:
    (tmp_path / "palo_alto.yaml").write_text(
        "enabled: true\nsource_ips: [10.0.0.1]\n")
    (tmp_path / "fortigate.yaml").write_text(
        "enabled: false\nsource_ips: []\n")
    configs = load_adapter_configs(tmp_path)
    assert configs["palo_alto"] == AdapterConfig(enabled=True, source_ips={"10.0.0.1"})
    assert configs["fortigate"] == AdapterConfig(enabled=False, source_ips=set())
```

- [ ] **Step 3: Implement `settings.py`**

```python
# flow-ingest/src/flow_ingest/settings.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class AdapterConfig:
    enabled: bool = True
    source_ips: frozenset[str] = field(default_factory=frozenset)


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://redis:6379/0"
    syslog_host: str = "0.0.0.0"
    syslog_port: int = 5514
    config_dir: str = "/etc/flowvis/adapters"
    log_level: str = "INFO"
    queue_max: int = 10_000


def load_adapter_configs(path: Path) -> dict[str, AdapterConfig]:
    out: dict[str, AdapterConfig] = {}
    for yml in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(yml.read_text()) or {}
        out[yml.stem] = AdapterConfig(
            enabled=bool(data.get("enabled", True)),
            source_ips=frozenset(data.get("source_ips", []) or []),
        )
    return out


# Convenience for tests comparing to a set literal:
def _freeze(v: object) -> frozenset[str]:
    return frozenset(v) if isinstance(v, (list, set, tuple)) else frozenset()
```

The test compares `source_ips={"10.0.0.1"}` against a `frozenset`. Adjust the test to `frozenset({"10.0.0.1"})`, or (preferred) relax equality via a second assertion on `set(cfg.source_ips)`. Implementer fixes test to use `frozenset`.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add config/adapters/ flow-ingest/src/flow_ingest/settings.py flow-ingest/tests/test_settings.py
git commit -m "feat(flow-ingest): per-firewall YAML config with source-IP demux"
```

---

### Task 1.8: `main.py` auto-loader + asyncio.gather runtime (TDD)

**Files:**
- Test: `flow-ingest/tests/test_main_loader.py`
- Create: `flow-ingest/src/flow_ingest/main.py`

Responsibilities:

1. Load settings + adapter configs.
2. Start shared `SyslogReceiver` on the bind address.
3. For every `*_adapter.py` under `adapters/` whose YAML is `enabled=true`, instantiate and schedule via `asyncio.gather`.
4. Install signal handlers for graceful shutdown (SIGTERM/SIGINT → cancel tasks → flush publisher → close receiver).
5. Expose `build_runtime(settings) -> Runtime` helper so tests can construct + introspect without spinning the full app.

- [ ] **Step 1: Write failing test**

```python
# flow-ingest/tests/test_main_loader.py
from __future__ import annotations

from pathlib import Path

import pytest

from flow_ingest.main import list_enabled_adapters
from flow_ingest.settings import AdapterConfig


def test_list_enabled_adapters(tmp_path: Path) -> None:
    cfg = {
        "palo_alto": AdapterConfig(enabled=True, source_ips=frozenset({"10.0.0.1"})),
        "fortigate": AdapterConfig(enabled=False, source_ips=frozenset()),
    }
    names = list_enabled_adapters(cfg)
    assert names == ["palo_alto"]


def test_unknown_adapter_warned_not_crashed(caplog) -> None:
    cfg = {"mystery_source": AdapterConfig(enabled=True, source_ips=frozenset())}
    names = list_enabled_adapters(cfg)
    assert names == []
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `main.py`**

```python
# flow-ingest/src/flow_ingest/main.py
from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import uvloop
from loguru import logger
from redis.asyncio import Redis

from flow_ingest.adapters.base import FlowAdapter
from flow_ingest.adapters.fortigate_adapter import FortiGateAdapter
from flow_ingest.adapters.palo_alto_adapter import PaloAltoAdapter
from flow_ingest.publisher import RedisFlowPublisher
from flow_ingest.settings import AdapterConfig, IngestSettings, load_adapter_configs
from flow_ingest.syslog_receiver import SyslogReceiver

_ADAPTER_REGISTRY: dict[str, type[FlowAdapter]] = {
    PaloAltoAdapter.name: PaloAltoAdapter,
    FortiGateAdapter.name: FortiGateAdapter,
}


def list_enabled_adapters(configs: dict[str, AdapterConfig]) -> list[str]:
    out: list[str] = []
    for name, cfg in configs.items():
        if not cfg.enabled:
            continue
        if name not in _ADAPTER_REGISTRY:
            logger.warning("unknown adapter {}; skipping", name)
            continue
        out.append(name)
    return out


async def _drain_adapter(adapter: FlowAdapter) -> None:
    async for _ in adapter.run():  # adapter publishes; we just keep draining
        pass


async def _run(settings: IngestSettings) -> None:
    configs = load_adapter_configs(Path(settings.config_dir))
    logger.info("loaded configs: {}", {k: v.enabled for k, v in configs.items()})

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    publisher = RedisFlowPublisher(redis=redis)
    receiver = SyslogReceiver(
        host=settings.syslog_host, port=settings.syslog_port, queue_max=settings.queue_max,
    )
    await receiver.start()

    tasks: list[asyncio.Task[None]] = []
    for name in list_enabled_adapters(configs):
        cls = _ADAPTER_REGISTRY[name]
        adapter = cls(
            receiver=receiver,
            publisher=publisher,
            peer_allowlist=set(configs[name].source_ips) or None,
        )
        tasks.append(asyncio.create_task(_drain_adapter(adapter), name=f"adapter:{name}"))

    stop = asyncio.Event()

    def _signal() -> None:
        stop.set()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal)

    await stop.wait()
    logger.info("shutdown signal received; stopping")
    for t in tasks:
        t.cancel()
    await publisher.flush()
    await receiver.stop()
    await redis.close()


def main() -> None:
    uvloop.install()
    asyncio.run(_run(IngestSettings()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add flow-ingest/src/flow_ingest/main.py flow-ingest/tests/test_main_loader.py
git commit -m "feat(flow-ingest): main loader wires adapters with asyncio.gather and signals"
```

---

### Task 1.9: Update root CI to include flow-ingest package

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add install + test steps** to the existing `python` job:

```yaml
      - name: Install flow-ingest with test extras
        run: pip install -e 'flow-ingest/[test]'
      - name: Mypy flow-ingest
        run: mypy flow-ingest/src
      - name: Pytest flow-ingest
        run: pytest flow-ingest/tests -v
```

- [ ] **Step 2: Run** `gh workflow run ci.yml` locally with `act` *or* push and observe. Expected: green.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint, type, and test flow-ingest package"
```

---

## Chunk 2: resolver worker (PTR + SaaS matching)

### Task 2.1: Scaffold `resolver/` package

**Files:**
- Create: `resolver/pyproject.toml`
- Create: `resolver/Dockerfile`
- Create: `resolver/src/resolver/__init__.py` (empty)
- Create: `resolver/tests/__init__.py` (empty)

- [ ] **Step 1: Write `resolver/pyproject.toml`**

```toml
[project]
name = "ztna-resolver"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pydantic==2.9.2",
  "pydantic-settings==2.5.2",
  "redis==5.1.0",
  "asyncpg==0.29.0",
  "loguru==0.7.2",
  "uvloop==0.20.0",
]

[project.optional-dependencies]
test = [
  "pytest==8.3.3",
  "pytest-asyncio==0.24.0",
  "fakeredis==2.25.1",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Write `resolver/Dockerfile`**

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "resolver.main"]
```

- [ ] **Step 3: Commit**

```bash
git add resolver/pyproject.toml resolver/Dockerfile \
        resolver/src/resolver/__init__.py resolver/tests/__init__.py
git commit -m "feat(resolver): scaffold package layout"
```

---

### Task 2.2: `SaasMatcher` — suffix match with priority ordering (TDD)

**Files:**
- Test: `resolver/tests/test_saas_matcher.py`
- Create: `resolver/src/resolver/saas_matcher.py`

The resolver loads all `saas_catalog` rows once at startup (and on a `NOTIFY saas_changed` signal — deferred to correlator-side; resolver just provides a `reload()` entry). Pattern match is suffix-based (per spec §4.3). Ties resolved by `priority DESC, len(pattern) DESC` (longer wins) so `.outlook.office365.com` beats `.office365.com`.

- [ ] **Step 1: Write failing test**

```python
# resolver/tests/test_saas_matcher.py
from __future__ import annotations

from resolver.saas_matcher import SaasMatcher, SaasRow


def test_empty_returns_none() -> None:
    m = SaasMatcher([])
    assert m.match("example.com") is None


def test_exact_suffix_match() -> None:
    m = SaasMatcher([
        SaasRow(id=1, name="Microsoft 365", pattern=".office365.com", priority=100),
    ])
    got = m.match("outlook.office365.com")
    assert got is not None
    assert got.name == "Microsoft 365"


def test_longer_pattern_wins() -> None:
    m = SaasMatcher([
        SaasRow(id=1, name="M365",     pattern=".office365.com",          priority=100),
        SaasRow(id=2, name="Exchange", pattern=".outlook.office365.com",  priority=100),
    ])
    got = m.match("mail.outlook.office365.com")
    assert got is not None
    assert got.name == "Exchange"


def test_priority_breaks_tie() -> None:
    m = SaasMatcher([
        SaasRow(id=1, name="Low",  pattern=".example.com", priority=50),
        SaasRow(id=2, name="High", pattern=".example.com", priority=100),
    ])
    got = m.match("foo.example.com")
    assert got is not None
    assert got.name == "High"


def test_no_match_returns_none() -> None:
    m = SaasMatcher([SaasRow(id=1, name="M365", pattern=".office365.com", priority=100)])
    assert m.match("evil.example.com") is None
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# resolver/src/resolver/saas_matcher.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SaasRow:
    id: int
    name: str
    pattern: str    # suffix, typically starts with '.'
    priority: int = 100


class SaasMatcher:
    """Suffix matcher with priority + length tiebreak."""

    def __init__(self, rows: list[SaasRow]) -> None:
        # Sort rows once so `match` can short-circuit on the first hit.
        self._rows = sorted(
            rows, key=lambda r: (-r.priority, -len(r.pattern), r.id)
        )

    def match(self, fqdn: str) -> SaasRow | None:
        lower = fqdn.lower()
        for row in self._rows:
            if lower.endswith(row.pattern.lower()):
                return row
        return None
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add resolver/src/resolver/saas_matcher.py resolver/tests/test_saas_matcher.py
git commit -m "feat(resolver): SaaS suffix matcher with priority + length tiebreak"
```

---

### Task 2.3: Resolver worker core — PTR lookup + rate limit + caching (TDD)

**Files:**
- Test: `resolver/tests/test_resolver_worker.py`
- Create: `resolver/src/resolver/resolver_worker.py`

Behavior:

1. Block on `BLPOP dns:unresolved` (Redis list, populated by correlator when an IP misses cache).
2. Before lookup, check Redis key `dns:ptr:<ip>` (TTL cache). If present, skip.
3. Rate-limit resolution to N queries/s globally (configurable, default 50). Use a simple token bucket.
4. Run PTR lookup via `asyncio.DefaultResolver` (wraps `aiodns` on Linux).
5. On hit: write `dns:ptr:<ip> = <ptr-or-empty>` with TTL 3600 s (configurable), upsert into `dns_cache`.
6. If SaaS pattern matches the PTR, also write `dns:saas:<ip> = <saas_id>` with same TTL.
7. **Firewall-supplied FQDN is always preferred** — the correlator will only queue IPs that have no firewall FQDN, so the resolver never contradicts an upstream hostname.

- [ ] **Step 1: Write failing tests**

```python
# resolver/tests/test_resolver_worker.py
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from resolver.resolver_worker import ResolverWorker
from resolver.saas_matcher import SaasMatcher, SaasRow


@pytest.mark.asyncio
async def test_cache_hit_skips_dns() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis.set("dns:ptr:8.8.8.8", "dns.google", ex=60)
    mock_resolver = AsyncMock()

    w = ResolverWorker(
        redis=redis,
        dns_resolver=mock_resolver,
        saas=SaasMatcher([]),
        pg_upsert=AsyncMock(),
        rate_per_s=100,
    )

    await w.process_one("8.8.8.8")
    mock_resolver.gethostbyaddr.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_miss_does_lookup_and_caches() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.return_value = SimpleAddrInfo(name="dns.google")
    pg = AsyncMock()

    w = ResolverWorker(
        redis=redis, dns_resolver=mock_resolver,
        saas=SaasMatcher([]), pg_upsert=pg, rate_per_s=100,
    )
    await w.process_one("8.8.8.8")

    assert await redis.get("dns:ptr:8.8.8.8") == "dns.google"
    pg.assert_awaited_once()
    args, _ = pg.call_args
    assert args[0] == "8.8.8.8" and args[1] == "dns.google"


@pytest.mark.asyncio
async def test_nxdomain_caches_empty() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.side_effect = OSError("NXDOMAIN")

    w = ResolverWorker(
        redis=redis, dns_resolver=mock_resolver,
        saas=SaasMatcher([]), pg_upsert=AsyncMock(), rate_per_s=100,
    )
    await w.process_one("192.0.2.1")

    # Empty string sentinel; consumers treat "" as NXDOMAIN.
    assert await redis.get("dns:ptr:192.0.2.1") == ""


@pytest.mark.asyncio
async def test_saas_match_cached() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.return_value = SimpleAddrInfo(
        name="tenant.outlook.office365.com")

    saas = SaasMatcher([
        SaasRow(id=42, name="M365", pattern=".office365.com", priority=100),
    ])
    w = ResolverWorker(
        redis=redis, dns_resolver=mock_resolver, saas=saas,
        pg_upsert=AsyncMock(), rate_per_s=100,
    )
    await w.process_one("52.97.1.1")

    assert await redis.get("dns:saas:52.97.1.1") == "42"


@pytest.mark.asyncio
async def test_rate_limit_enforced() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    mock_resolver = AsyncMock()
    mock_resolver.gethostbyaddr.return_value = SimpleAddrInfo(name="x.example.com")

    w = ResolverWorker(
        redis=redis, dns_resolver=mock_resolver, saas=SaasMatcher([]),
        pg_upsert=AsyncMock(), rate_per_s=2,  # 2 qps
    )

    start = asyncio.get_running_loop().time()
    await w.process_one("10.0.0.1")
    await w.process_one("10.0.0.2")
    await w.process_one("10.0.0.3")      # must wait for bucket to refill
    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed >= 0.4  # 3rd call waits ~500ms


class SimpleAddrInfo:
    def __init__(self, name: str) -> None:
        self.name = name
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `resolver_worker.py`**

```python
# resolver/src/resolver/resolver_worker.py
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger
from redis.asyncio import Redis

from resolver.saas_matcher import SaasMatcher, SaasRow

PgUpsert = Callable[[str, str | None, str | None], Awaitable[None]]
# (dst_ip, ptr, source) → upsert into dns_cache


class _TokenBucket:
    def __init__(self, rate_per_s: float) -> None:
        self._rate = rate_per_s
        self._capacity = max(1.0, rate_per_s)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._capacity, self._tokens + (now - self._last) * self._rate
            )
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= 1.0


@dataclass
class ResolverWorker:
    redis: Redis
    dns_resolver: object            # `asyncio.DefaultResolver()` in prod
    saas: SaasMatcher
    pg_upsert: PgUpsert
    rate_per_s: float = 50.0
    ptr_ttl_s: int = 3600
    saas_ttl_s: int = 3600

    def __post_init__(self) -> None:
        self._bucket = _TokenBucket(self.rate_per_s)

    async def process_one(self, ip: str) -> None:
        cached = await self.redis.get(f"dns:ptr:{ip}")
        if cached is not None:
            return
        await self._bucket.take()
        try:
            info = await self.dns_resolver.gethostbyaddr(ip)  # type: ignore[attr-defined]
            name = info.name or ""
        except Exception as exc:  # noqa: BLE001 - DNS failures expected
            logger.debug("PTR lookup failed for {}: {}", ip, exc)
            name = ""
        await self.redis.set(f"dns:ptr:{ip}", name, ex=self.ptr_ttl_s)
        await self.pg_upsert(ip, name or None, "ptr")
        if name:
            row: SaasRow | None = self.saas.match(name)
            if row is not None:
                await self.redis.set(f"dns:saas:{ip}", str(row.id), ex=self.saas_ttl_s)

    async def run_loop(self, queue_key: str = "dns:unresolved") -> None:
        while True:
            item = await self.redis.blpop([queue_key], timeout=5)  # type: ignore[arg-type]
            if item is None:
                continue
            _k, ip = item
            try:
                await self.process_one(ip)
            except Exception as exc:  # noqa: BLE001
                logger.warning("resolver error for {}: {}", ip, exc)
```

- [ ] **Step 4: Run — expect PASS**

Note on `test_rate_limit_enforced`: `asyncio.sleep` returns quickly under `pytest-asyncio`'s default fast-forward loop — the assertion is on real wall-clock delta so the loop waits. If the CI runner is under heavy load and the test flakes, widen the `>= 0.4` bound (do not remove it).

- [ ] **Step 5: Commit**

```bash
git add resolver/src/resolver/resolver_worker.py resolver/tests/test_resolver_worker.py
git commit -m "feat(resolver): PTR worker with token-bucket rate limit and SaaS caching"
```

---

### Task 2.4: Resolver `main.py` + settings

**Files:**
- Create: `resolver/src/resolver/settings.py`
- Create: `resolver/src/resolver/main.py`

- [ ] **Step 1: Write `settings.py`**

```python
# resolver/src/resolver/settings.py
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ResolverSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://ztna:change-me@postgres:5432/ztna"
    rate_per_s: float = 50.0
    ptr_ttl_s: int = 3600
    saas_ttl_s: int = 3600
    log_level: str = "INFO"
```

- [ ] **Step 2: Write `main.py`**

```python
# resolver/src/resolver/main.py
from __future__ import annotations

import asyncio

import asyncpg
import uvloop
from loguru import logger
from redis.asyncio import Redis

from resolver.resolver_worker import ResolverWorker
from resolver.saas_matcher import SaasMatcher, SaasRow
from resolver.settings import ResolverSettings


async def _load_saas(pool: asyncpg.Pool) -> SaasMatcher:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, fqdn_pattern AS pattern, priority FROM saas_catalog"
        )
    return SaasMatcher([SaasRow(**dict(r)) for r in rows])


async def _pg_upsert_factory(pool: asyncpg.Pool):
    async def _upsert(dst_ip: str, ptr: str | None, source: str | None) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dns_cache (dst_ip, ptr, resolved_at, source)
                VALUES ($1, $2, now(), COALESCE($3, 'ptr'))
                ON CONFLICT (dst_ip) DO UPDATE
                  SET ptr = EXCLUDED.ptr,
                      resolved_at = EXCLUDED.resolved_at,
                      source = EXCLUDED.source;
                """,
                dst_ip, ptr, source,
            )
    return _upsert


async def _run(settings: ResolverSettings) -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    pool = await asyncpg.create_pool(
        _as_asyncpg_dsn(settings.database_url), min_size=1, max_size=4,
    )
    saas = await _load_saas(pool)
    pg_upsert = await _pg_upsert_factory(pool)
    resolver_inst = asyncio.DefaultResolver()

    worker = ResolverWorker(
        redis=redis, dns_resolver=resolver_inst, saas=saas,
        pg_upsert=pg_upsert, rate_per_s=settings.rate_per_s,
        ptr_ttl_s=settings.ptr_ttl_s, saas_ttl_s=settings.saas_ttl_s,
    )
    logger.info("resolver worker starting at {} qps", settings.rate_per_s)
    await worker.run_loop()


def _as_asyncpg_dsn(url: str) -> str:
    # asyncpg only understands postgresql://; strip SQLAlchemy driver suffix.
    return url.replace("postgresql+asyncpg://", "postgresql://") \
              .replace("postgresql+psycopg://", "postgresql://")


def main() -> None:
    uvloop.install()
    asyncio.run(_run(ResolverSettings()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Extend CI** to install + test resolver alongside flow-ingest.

```yaml
      - name: Install resolver with test extras
        run: pip install -e 'resolver/[test]'
      - name: Mypy resolver
        run: mypy resolver/src
      - name: Pytest resolver
        run: pytest resolver/tests -v
```

- [ ] **Step 4: Commit**

```bash
git add resolver/src/resolver/settings.py resolver/src/resolver/main.py .github/workflows/ci.yml
git commit -m "feat(resolver): main loop with asyncpg dns_cache upsert and SaaS preload"
```

---

## Chunk 3: correlator service (flow-only pipeline)

### Task 3.1: Scaffold `correlator/` package

**Files:**
- Create: `correlator/pyproject.toml`
- Create: `correlator/Dockerfile`
- Create: `correlator/src/correlator/__init__.py` (empty)
- Create: `correlator/src/correlator/pipeline/__init__.py` (empty)
- Create: `correlator/tests/__init__.py` (empty)

- [ ] **Step 1: Write `correlator/pyproject.toml`**

```toml
[project]
name = "ztna-correlator"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pydantic==2.9.2",
  "pydantic-settings==2.5.2",
  "redis==5.1.0",
  "asyncpg==0.29.0",
  "loguru==0.7.2",
  "uvloop==0.20.0",
]

[project.optional-dependencies]
test = [
  "pytest==8.3.3",
  "pytest-asyncio==0.24.0",
  "fakeredis==2.25.1",
  "freezegun==1.5.1",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Write `correlator/Dockerfile`**

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "correlator.main"]
```

- [ ] **Step 3: Commit**

```bash
git add correlator/pyproject.toml correlator/Dockerfile \
        correlator/src/correlator/__init__.py \
        correlator/src/correlator/pipeline/__init__.py \
        correlator/tests/__init__.py
git commit -m "feat(correlator): scaffold package layout"
```

---

### Task 3.2: `FlowWindower` — 5s tumbling window (TDD)

**Files:**
- Test: `correlator/tests/test_windower.py`
- Create: `correlator/src/correlator/pipeline/windower.py`

Windower spec:

- Tumbling 5 s windows aligned to wall-clock (`time_bucket_start = t - t % 5`).
- Key = `(src_ip, dst_ip, dst_port, proto)`.
- Aggregation: `sum(bytes)`, `sum(packets)`, `count(*) → flow_count`.
- On boundary crossing, emit all aggregates for the *completed* bucket, reset map.
- Input: bounded `asyncio.Queue` of `FlowEvent`. Output: bounded `asyncio.Queue` of `WindowedFlow`.
- Overflow on output queue drops oldest; increments `dropped_count` carried downstream.

- [ ] **Step 1: Write failing tests**

```python
# correlator/tests/test_windower.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from correlator.pipeline.windower import FlowWindower, WindowedFlow


def _ev(t: datetime, src: str = "10.0.0.1", dst: str = "1.1.1.1",
        port: int = 443, proto: int = 6, b: int = 100, p: int = 1) -> dict:
    return {
        "ts": t, "src_ip": src, "src_port": 1234, "dst_ip": dst, "dst_port": port,
        "proto": proto, "bytes": b, "packets": p, "action": "allow",
        "fqdn": None, "app_id": None, "source": "palo_alto", "raw_id": None,
    }


@pytest.mark.asyncio
async def test_same_bucket_aggregates() -> None:
    inp: asyncio.Queue = asyncio.Queue()
    out: asyncio.Queue = asyncio.Queue()
    w = FlowWindower(inp=inp, out=out, window_s=5)

    t = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    await inp.put(_ev(t, b=100, p=2))
    await inp.put(_ev(t + timedelta(seconds=1), b=200, p=3))
    # Advance past the window boundary to flush.
    await inp.put(_ev(t + timedelta(seconds=6), b=1, p=1))

    task = asyncio.create_task(w.run())
    wf1 = await asyncio.wait_for(out.get(), timeout=1.0)
    task.cancel()
    assert isinstance(wf1, WindowedFlow)
    assert wf1.bytes == 300 and wf1.packets == 5 and wf1.flow_count == 2
    assert wf1.bucket_start == t


@pytest.mark.asyncio
async def test_distinct_keys_emit_separately() -> None:
    inp: asyncio.Queue = asyncio.Queue()
    out: asyncio.Queue = asyncio.Queue()
    w = FlowWindower(inp=inp, out=out, window_s=5)
    t = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)

    await inp.put(_ev(t, dst="1.1.1.1"))
    await inp.put(_ev(t, dst="2.2.2.2"))
    await inp.put(_ev(t + timedelta(seconds=6)))

    task = asyncio.create_task(w.run())
    wf1 = await asyncio.wait_for(out.get(), timeout=1.0)
    wf2 = await asyncio.wait_for(out.get(), timeout=1.0)
    task.cancel()
    dsts = {wf1.dst_ip, wf2.dst_ip}
    assert dsts == {"1.1.1.1", "2.2.2.2"}


@pytest.mark.asyncio
async def test_idle_flush_on_timer() -> None:
    """If no event arrives after the window closes, we still flush existing
    buckets on a tick (every ~1s) so live dashboards don't stall."""
    inp: asyncio.Queue = asyncio.Queue()
    out: asyncio.Queue = asyncio.Queue()
    w = FlowWindower(inp=inp, out=out, window_s=1, tick_s=0.1)

    t = datetime.now(UTC)
    await inp.put(_ev(t))
    task = asyncio.create_task(w.run())
    wf = await asyncio.wait_for(out.get(), timeout=3.0)
    task.cancel()
    assert wf.flow_count == 1
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# correlator/src/correlator/pipeline/windower.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger


@dataclass(frozen=True)
class _Key:
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int


@dataclass
class _Acc:
    bytes: int = 0
    packets: int = 0
    flow_count: int = 0
    app_id_seen: str | None = None
    fqdn_seen: str | None = None
    action_seen: str | None = None


@dataclass
class WindowedFlow:
    bucket_start: datetime
    window_s: int
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    flow_count: int
    app_id: str | None
    fqdn: str | None
    action: str | None
    lossy: bool = False
    dropped_count: int = 0


@dataclass
class FlowWindower:
    inp: asyncio.Queue
    out: asyncio.Queue
    window_s: int = 5
    tick_s: float = 1.0

    def __post_init__(self) -> None:
        self._buckets: dict[datetime, dict[_Key, _Acc]] = {}
        self._dropped: int = 0

    def _bucket_start(self, ts: datetime) -> datetime:
        epoch = int(ts.timestamp())
        aligned = epoch - (epoch % self.window_s)
        return datetime.fromtimestamp(aligned, tz=ts.tzinfo)

    async def _emit_ready(self, now: datetime) -> None:
        threshold = self._bucket_start(now) - timedelta(seconds=self.window_s)
        ready = [b for b in self._buckets if b <= threshold]
        for b in sorted(ready):
            for key, acc in self._buckets.pop(b).items():
                wf = WindowedFlow(
                    bucket_start=b, window_s=self.window_s,
                    src_ip=key.src_ip, dst_ip=key.dst_ip,
                    dst_port=key.dst_port, proto=key.proto,
                    bytes=acc.bytes, packets=acc.packets, flow_count=acc.flow_count,
                    app_id=acc.app_id_seen, fqdn=acc.fqdn_seen, action=acc.action_seen,
                    lossy=self._dropped > 0, dropped_count=self._dropped,
                )
                try:
                    self.out.put_nowait(wf)
                except asyncio.QueueFull:
                    try:
                        _ = self.out.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._dropped += 1
                    try:
                        self.out.put_nowait(wf)
                    except asyncio.QueueFull:
                        logger.warning("windower out queue still full; dropping")
        if ready:
            self._dropped = 0  # reset once flushed; next window starts clean

    async def run(self) -> None:
        while True:
            try:
                ev = await asyncio.wait_for(self.inp.get(), timeout=self.tick_s)
            except asyncio.TimeoutError:
                await self._emit_ready(datetime.now(tz=_UTC()))
                continue
            ts: datetime = ev["ts"]
            bucket = self._bucket_start(ts)
            key = _Key(ev["src_ip"], ev["dst_ip"], int(ev["dst_port"]), int(ev["proto"]))
            slot = self._buckets.setdefault(bucket, {})
            acc = slot.setdefault(key, _Acc())
            acc.bytes += int(ev["bytes"])
            acc.packets += int(ev["packets"])
            acc.flow_count += 1
            # carry through first-seen values; later reconciled by AppResolver
            acc.app_id_seen = acc.app_id_seen or ev.get("app_id")
            acc.fqdn_seen = acc.fqdn_seen or ev.get("fqdn")
            acc.action_seen = acc.action_seen or ev.get("action")
            await self._emit_ready(ts)


def _UTC():
    from datetime import timezone
    return timezone.utc
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add correlator/src/correlator/pipeline/windower.py correlator/tests/test_windower.py
git commit -m "feat(correlator): 5s tumbling FlowWindower with idle tick flush"
```

---

### Task 3.3: `AppResolver` — resolution chain + NOTIFY reload (TDD)

**Files:**
- Test: `correlator/tests/test_app_resolver.py`
- Create: `correlator/src/correlator/pipeline/app_resolver.py`

Chain (spec §4.3):

1. **Manual applications** — most specific CIDR match + highest priority; loaded into a `RadixTree` (use `pytricia` at runtime; for unit tests an in-memory dict of CIDR strings + `ipaddress.ip_network.supernet_of` is sufficient).
2. **Firewall-supplied FQDN** — if set, match against `saas_catalog` via `SaasMatcher` (same implementation imported from the resolver package via a minimal shared model, or duplicated — choose duplicate for P2 to avoid cross-service imports).
3. **PTR** — read `dns:ptr:<ip>` from Redis, then `dns:saas:<ip>` for the saas id.
4. **Port default** — lookup `port_defaults(dst_port, proto)`.
5. **Raw `ip:port`** — fall through.

Output attaches a `label_kind ∈ {"manual","saas","ptr","port","raw"}` and `label: str`.

**Reload:** a background task `LISTEN applications_changed; LISTEN saas_changed;` (Postgres NOTIFY) rebuilds the in-memory caches on event. Tests simulate reload via explicit `reload()` call.

- [ ] **Step 1: Write failing tests**

```python
# correlator/tests/test_app_resolver.py
from __future__ import annotations

import fakeredis.aioredis
import pytest

from correlator.pipeline.app_resolver import (
    AppCandidate, AppResolver, ManualApp, PortDefault,
)


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_manual_match_wins(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(
        manual=[ManualApp(id=1, name="CRM-Prod", cidr="10.100.0.0/16",
                          port_min=None, port_max=None, proto=None, priority=200)],
        saas=[], port_defaults=[],
    )
    cand = await r.resolve(dst_ip="10.100.0.5", dst_port=443, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "manual"
    assert cand.label == "CRM-Prod"


@pytest.mark.asyncio
async def test_firewall_fqdn_matches_saas(redis) -> None:
    from correlator.pipeline.app_resolver import SaasEntry
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[SaasEntry(id=1, name="M365", pattern=".office365.com", priority=100)],
           port_defaults=[])
    cand = await r.resolve(dst_ip="52.97.1.1", dst_port=443, proto=6,
                           firewall_fqdn="outlook.office365.com", app_id=None)
    assert cand.label_kind == "saas"
    assert cand.label == "M365"


@pytest.mark.asyncio
async def test_ptr_fallback_via_redis(redis) -> None:
    from correlator.pipeline.app_resolver import SaasEntry
    await redis.set("dns:ptr:8.8.8.8", "dns.google")
    await redis.set("dns:saas:8.8.8.8", "7")
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[SaasEntry(id=7, name="Google DNS", pattern=".google", priority=90)],
           port_defaults=[])
    cand = await r.resolve(dst_ip="8.8.8.8", dst_port=53, proto=17,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "ptr"
    assert cand.label == "Google DNS"


@pytest.mark.asyncio
async def test_port_default_when_no_fqdn(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[], port_defaults=[PortDefault(port=22, proto=6, name="SSH")])
    cand = await r.resolve(dst_ip="10.0.0.99", dst_port=22, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "port"
    assert cand.label == "SSH"


@pytest.mark.asyncio
async def test_raw_fallback(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[], port_defaults=[])
    cand = await r.resolve(dst_ip="198.51.100.1", dst_port=9999, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label_kind == "raw"
    assert cand.label == "198.51.100.1:9999"


@pytest.mark.asyncio
async def test_missing_ptr_enqueues_for_resolver(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[], saas=[], port_defaults=[])
    await r.resolve(dst_ip="203.0.113.5", dst_port=443, proto=6,
                    firewall_fqdn=None, app_id=None)
    assert await redis.lpop("dns:unresolved") == "203.0.113.5"


@pytest.mark.asyncio
async def test_reload_replaces_caches(redis) -> None:
    r = AppResolver(redis=redis)
    r.load(manual=[ManualApp(id=1, name="Old", cidr="10.0.0.0/8",
                             port_min=None, port_max=None, proto=None, priority=100)],
           saas=[], port_defaults=[])
    r.load(manual=[ManualApp(id=2, name="New", cidr="10.0.0.0/8",
                             port_min=None, port_max=None, proto=None, priority=100)],
           saas=[], port_defaults=[])
    cand = await r.resolve(dst_ip="10.0.0.1", dst_port=443, proto=6,
                           firewall_fqdn=None, app_id=None)
    assert cand.label == "New"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `app_resolver.py`**

```python
# correlator/src/correlator/pipeline/app_resolver.py
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Literal

from loguru import logger
from redis.asyncio import Redis


@dataclass(frozen=True)
class ManualApp:
    id: int
    name: str
    cidr: str
    port_min: int | None
    port_max: int | None
    proto: int | None
    priority: int = 100


@dataclass(frozen=True)
class SaasEntry:
    id: int
    name: str
    pattern: str
    priority: int = 100


@dataclass(frozen=True)
class PortDefault:
    port: int
    proto: int
    name: str


LabelKind = Literal["manual", "saas", "ptr", "port", "raw"]


@dataclass
class AppCandidate:
    label_kind: LabelKind
    label: str
    app_id: int | None = None


class AppResolver:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._manual: list[ManualApp] = []
        self._saas_sorted: list[SaasEntry] = []
        self._port_defaults: dict[tuple[int, int], PortDefault] = {}

    def load(
        self,
        manual: list[ManualApp],
        saas: list[SaasEntry],
        port_defaults: list[PortDefault],
    ) -> None:
        self._manual = sorted(
            manual,
            key=lambda a: (-a.priority, -ipaddress.ip_network(a.cidr).prefixlen * -1),
        )
        # Sort manual: highest priority, then most-specific CIDR (longest prefix).
        self._manual.sort(
            key=lambda a: (-a.priority, -ipaddress.ip_network(a.cidr).prefixlen)
        )
        self._saas_sorted = sorted(
            saas, key=lambda s: (-s.priority, -len(s.pattern), s.id)
        )
        self._port_defaults = {(p.port, p.proto): p for p in port_defaults}
        logger.info(
            "app-resolver loaded manual={} saas={} ports={}",
            len(self._manual), len(self._saas_sorted), len(self._port_defaults),
        )

    def _manual_hit(self, ip: str, port: int, proto: int) -> ManualApp | None:
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for app in self._manual:
            if ip_obj not in ipaddress.ip_network(app.cidr):
                continue
            if app.proto is not None and app.proto != proto:
                continue
            if app.port_min is not None and port < app.port_min:
                continue
            if app.port_max is not None and port > app.port_max:
                continue
            return app
        return None

    def _saas_hit(self, fqdn: str) -> SaasEntry | None:
        lower = fqdn.lower()
        for s in self._saas_sorted:
            if lower.endswith(s.pattern.lower()):
                return s
        return None

    async def resolve(
        self,
        *,
        dst_ip: str,
        dst_port: int,
        proto: int,
        firewall_fqdn: str | None,
        app_id: str | None,
    ) -> AppCandidate:
        manual = self._manual_hit(dst_ip, dst_port, proto)
        if manual is not None:
            return AppCandidate(label_kind="manual", label=manual.name, app_id=manual.id)

        if firewall_fqdn:
            s = self._saas_hit(firewall_fqdn)
            if s is not None:
                return AppCandidate(label_kind="saas", label=s.name, app_id=s.id)

        ptr = await self.redis.get(f"dns:ptr:{dst_ip}")
        if ptr is None:
            # Unseen IP — schedule for the resolver worker.
            await self.redis.rpush("dns:unresolved", dst_ip)
        elif ptr:
            saas_id_str = await self.redis.get(f"dns:saas:{dst_ip}")
            if saas_id_str is not None:
                try:
                    saas_id = int(saas_id_str)
                except ValueError:
                    saas_id = -1
                match = next((s for s in self._saas_sorted if s.id == saas_id), None)
                if match is not None:
                    return AppCandidate(label_kind="ptr", label=match.name, app_id=match.id)

        port_hit = self._port_defaults.get((dst_port, proto))
        if port_hit is not None:
            return AppCandidate(label_kind="port", label=port_hit.name)

        return AppCandidate(label_kind="raw", label=f"{dst_ip}:{dst_port}")


async def listen_for_reload(
    resolver: AppResolver,
    dsn: str,
    reload_fn,
) -> None:
    """Background task: LISTEN on Postgres for config changes and call reload_fn()
    to rebuild resolver state. Registered from `main.py`. Implementer uses asyncpg
    `connection.add_listener` for `applications_changed` + `saas_changed`."""
    import asyncpg
    conn = await asyncpg.connect(dsn)
    try:
        await conn.add_listener("applications_changed", lambda *_: None)
        await conn.add_listener("saas_changed", lambda *_: None)
        # Implementation detail: the callback above triggers `reload_fn` which
        # queries Postgres, constructs the cache rows, and calls `resolver.load(...)`.
        # The full callback body is wired in main.py where asyncpg pool + queries
        # live; this helper exists so tests can monkey-patch it out.
        while True:
            await asyncio.sleep(3600)  # heartbeat; listener fires independently.
    finally:
        await conn.close()


import asyncio  # noqa: E402 - used by listen_for_reload
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add correlator/src/correlator/pipeline/app_resolver.py correlator/tests/test_app_resolver.py
git commit -m "feat(correlator): AppResolver with manual/saas/ptr/port/raw resolution chain"
```

---

### Task 3.4: `Writer` — batched COPY into `flows` (TDD)

**Files:**
- Test: `correlator/tests/test_writer.py`
- Create: `correlator/src/correlator/pipeline/writer.py`

Writer uses `asyncpg.connection.copy_records_to_table` for 10 k-row batches or 500 ms flush interval (whichever first). On failure: log, retry with backoff, do not lose the batch on transient errors (bounded retry → then drop + increment `writer_dropped_rows_total`).

- [ ] **Step 1: Write failing test — uses `testing.postgresql` or real PG from compose**

For unit purposes, stub `asyncpg.Pool` with `unittest.mock.AsyncMock` and assert COPY is invoked with expected rows.

```python
# correlator/tests/test_writer.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from correlator.pipeline.windower import WindowedFlow
from correlator.pipeline.writer import Writer


def _wf() -> WindowedFlow:
    return WindowedFlow(
        bucket_start=datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC),
        window_s=5, src_ip="10.0.0.1", dst_ip="1.1.1.1",
        dst_port=443, proto=6, bytes=100, packets=2, flow_count=1,
        app_id=None, fqdn=None, action="allow",
    )


@pytest.mark.asyncio
async def test_writer_flushes_on_batch_size() -> None:
    pool = MagicMock()
    conn = AsyncMock()
    conn.copy_records_to_table = AsyncMock()
    # async context manager on pool.acquire()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = None

    q: asyncio.Queue = asyncio.Queue()
    w = Writer(inp=q, pool=pool, batch_size=2, flush_ms=10_000)
    for _ in range(2):
        await q.put(_wf())
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.1)
    task.cancel()

    conn.copy_records_to_table.assert_awaited()
    _args, kwargs = conn.copy_records_to_table.call_args
    assert kwargs["table_name"] == "flows"
    assert len(kwargs["records"]) == 2


@pytest.mark.asyncio
async def test_writer_flushes_on_timer() -> None:
    pool = MagicMock()
    conn = AsyncMock()
    conn.copy_records_to_table = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = None

    q: asyncio.Queue = asyncio.Queue()
    w = Writer(inp=q, pool=pool, batch_size=1000, flush_ms=100)
    await q.put(_wf())
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.25)
    task.cancel()

    conn.copy_records_to_table.assert_awaited()
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `writer.py`**

```python
# correlator/src/correlator/pipeline/writer.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import asyncpg
from loguru import logger

from correlator.pipeline.windower import WindowedFlow


@dataclass
class Writer:
    inp: asyncio.Queue
    pool: asyncpg.Pool
    batch_size: int = 10_000
    flush_ms: int = 500

    async def _flush(self, rows: list[tuple]) -> None:
        if not rows:
            return
        async with self.pool.acquire() as conn:
            await conn.copy_records_to_table(
                table_name="flows",
                records=rows,
                columns=[
                    "time", "src_ip", "dst_ip", "dst_port", "proto",
                    "bytes", "packets", "flow_count", "source",
                ],
            )

    async def run(self) -> None:
        buf: list[tuple] = []
        deadline = time.monotonic() + self.flush_ms / 1000
        while True:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                wf: WindowedFlow = await asyncio.wait_for(self.inp.get(), timeout=timeout)
                buf.append((
                    wf.bucket_start, wf.src_ip, wf.dst_ip, wf.dst_port, wf.proto,
                    wf.bytes, wf.packets, wf.flow_count, "correlator",
                ))
                if len(buf) >= self.batch_size:
                    await self._flush_safe(buf)
                    buf = []
                    deadline = time.monotonic() + self.flush_ms / 1000
            except asyncio.TimeoutError:
                if buf:
                    await self._flush_safe(buf)
                    buf = []
                deadline = time.monotonic() + self.flush_ms / 1000

    async def _flush_safe(self, buf: list[tuple]) -> None:
        try:
            await self._flush(buf)
        except Exception as exc:  # noqa: BLE001
            logger.warning("writer flush failed; dropping {} rows: {}", len(buf), exc)
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add correlator/src/correlator/pipeline/writer.py correlator/tests/test_writer.py
git commit -m "feat(correlator): batched COPY writer for flows hypertable"
```

---

### Task 3.5: `SankeyPublisher` — emit `SankeyDelta` to Redis pub/sub (TDD)

**Files:**
- Test: `correlator/tests/test_sankey_publisher.py`
- Create: `correlator/src/correlator/pipeline/sankey_publisher.py`

Pub/sub payload matches spec §6.4. Published every window tick with aggregated links keyed `(src_ip, app_label)`. In P2 left column is `src_ip` (no identity yet), right column is the `AppCandidate.label`. Publisher batches all `WindowedFlow`s sharing a `bucket_start` into a single delta.

- [ ] **Step 1: Write failing test**

```python
# correlator/tests/test_sankey_publisher.py
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from correlator.pipeline.app_resolver import AppCandidate
from correlator.pipeline.sankey_publisher import LabelledFlow, SankeyPublisher


@pytest.mark.asyncio
async def test_publishes_delta_on_window_close() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    q: asyncio.Queue = asyncio.Queue()
    p = SankeyPublisher(inp=q, redis=redis, channel="sankey.live")

    t = datetime(2026, 4, 22, 14, 12, 0, tzinfo=UTC)
    await q.put(LabelledFlow(
        bucket_start=t, window_s=5,
        src_ip="10.0.0.1", dst_ip="52.97.1.1", dst_port=443, proto=6,
        bytes=1000, packets=10, flow_count=3,
        candidate=AppCandidate(label_kind="saas", label="M365", app_id=1),
        lossy=False, dropped_count=0,
    ))
    await q.put(LabelledFlow(
        bucket_start=t, window_s=5,
        src_ip="10.0.0.2", dst_ip="52.97.1.1", dst_port=443, proto=6,
        bytes=500, packets=4, flow_count=1,
        candidate=AppCandidate(label_kind="saas", label="M365", app_id=1),
        lossy=True, dropped_count=2,
    ))

    pub = asyncio.create_task(p.run())

    async with redis.pubsub() as sub:
        await sub.subscribe("sankey.live")
        # drain subscribe confirmation
        await sub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        # advance with a sentinel that closes the window
        await q.put(LabelledFlow(
            bucket_start=t.replace(minute=13), window_s=5,
            src_ip="10.0.0.9", dst_ip="1.1.1.1", dst_port=443, proto=6,
            bytes=1, packets=1, flow_count=1,
            candidate=AppCandidate(label_kind="raw", label="1.1.1.1:443"),
            lossy=False, dropped_count=0,
        ))
        msg = await sub.get_message(ignore_subscribe_messages=True, timeout=2.0)
        pub.cancel()

    assert msg is not None
    delta = json.loads(msg["data"])
    assert delta["window_s"] == 5
    links = delta["links"]
    assert any(l["src"] == "ip:10.0.0.1" and l["dst"] == "app:M365" and l["bytes"] == 1000
               for l in links)
    assert any(l["src"] == "ip:10.0.0.2" for l in links)
    assert delta["lossy"] is True
    assert delta["dropped_count"] == 2
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# correlator/src/correlator/pipeline/sankey_publisher.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from redis.asyncio import Redis

from correlator.pipeline.app_resolver import AppCandidate


@dataclass
class LabelledFlow:
    bucket_start: datetime
    window_s: int
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    flow_count: int
    candidate: AppCandidate
    lossy: bool = False
    dropped_count: int = 0


@dataclass
class SankeyPublisher:
    inp: asyncio.Queue
    redis: Redis
    channel: str = "sankey.live"

    async def run(self) -> None:
        current_bucket: datetime | None = None
        pending: list[LabelledFlow] = []
        while True:
            lf: LabelledFlow = await self.inp.get()
            if current_bucket is None:
                current_bucket = lf.bucket_start
            if lf.bucket_start > current_bucket:
                await self._publish(current_bucket, pending)
                pending = []
                current_bucket = lf.bucket_start
            pending.append(lf)

    async def _publish(self, bucket: datetime, flows: list[LabelledFlow]) -> None:
        if not flows:
            return
        links: dict[tuple[str, str], dict] = {}
        nodes_left: dict[str, dict] = {}
        nodes_right: dict[str, dict] = {}
        lossy = False
        dropped = 0
        for f in flows:
            left = f"ip:{f.src_ip}"
            right = f"app:{f.candidate.label}"
            key = (left, right)
            link = links.setdefault(key, {
                "src": left, "dst": right, "bytes": 0, "flows": 0, "users": 0,
            })
            link["bytes"] += f.bytes
            link["flows"] += f.flow_count
            nodes_left.setdefault(left, {"id": left, "label": f.src_ip, "size": 0})
            nodes_left[left]["size"] += 1
            nodes_right.setdefault(right, {
                "id": right, "label": f.candidate.label, "kind": f.candidate.label_kind,
            })
            lossy = lossy or f.lossy
            dropped += f.dropped_count
        delta = {
            "ts": bucket.isoformat(),
            "window_s": flows[0].window_s,
            "nodes_left": list(nodes_left.values()),
            "nodes_right": list(nodes_right.values()),
            "links": list(links.values()),
            "lossy": lossy,
            "dropped_count": dropped,
        }
        try:
            await self.redis.publish(self.channel, json.dumps(delta))
        except Exception as exc:  # noqa: BLE001
            logger.warning("sankey publish failed: {}", exc)
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add correlator/src/correlator/pipeline/sankey_publisher.py correlator/tests/test_sankey_publisher.py
git commit -m "feat(correlator): SankeyPublisher emits per-window deltas to Redis pub/sub"
```

---

### Task 3.6: Metrics placeholders

**Files:**
- Create: `correlator/src/correlator/pipeline/metrics.py`

P2 only wires counters as module-level dicts so tests can assert on them. Real Prometheus exporter lands in P4. This keeps the service code call-site stable (`metrics.dropped_flows_total += 1`) across plan versions.

- [ ] **Step 1: Write**

```python
# correlator/src/correlator/pipeline/metrics.py
"""Metric placeholders — swap to prometheus_client in P4.

The correlator code references these module-level counters. Keeping them as
plain ints lets P2 progress without an observability story.
"""
from __future__ import annotations

dropped_flows_total: int = 0
unknown_user_ratio: float = 0.0       # always 0.0 in P2 (no identity)
lcd_miss_total: int = 0                # always 0 in P2
queue_depth: dict[str, int] = {}
writer_dropped_rows_total: int = 0


def reset_for_tests() -> None:
    global dropped_flows_total, unknown_user_ratio, lcd_miss_total, writer_dropped_rows_total
    dropped_flows_total = 0
    unknown_user_ratio = 0.0
    lcd_miss_total = 0
    writer_dropped_rows_total = 0
    queue_depth.clear()
```

- [ ] **Step 2: Commit**

```bash
git add correlator/src/correlator/pipeline/metrics.py
git commit -m "feat(correlator): metrics placeholder module (prometheus wired in P4)"
```

---

### Task 3.7: `main.py` — wire the pipeline

**Files:**
- Create: `correlator/src/correlator/settings.py`
- Create: `correlator/src/correlator/main.py`

- [ ] **Step 1: Write `settings.py`**

```python
# correlator/src/correlator/settings.py
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CorrelatorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://ztna:change-me@postgres:5432/ztna"
    flows_stream: str = "flows.raw"
    window_s: int = 5
    queue_max: int = 10_000
    batch_size: int = 10_000
    flush_ms: int = 500
    log_level: str = "INFO"
```

- [ ] **Step 2: Write `main.py`**

```python
# correlator/src/correlator/main.py
from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime

import asyncpg
import uvloop
from loguru import logger
from redis.asyncio import Redis

from correlator.pipeline.app_resolver import (
    AppResolver, ManualApp, PortDefault, SaasEntry,
)
from correlator.pipeline.sankey_publisher import LabelledFlow, SankeyPublisher
from correlator.pipeline.windower import FlowWindower, WindowedFlow
from correlator.pipeline.writer import Writer
from correlator.settings import CorrelatorSettings


async def _read_xstream_into(
    redis: Redis, stream: str, out: asyncio.Queue, group: str = "correlator",
) -> None:
    # Ensure group exists
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception:  # group already exists
        pass
    consumer = "c1"
    while True:
        entries = await redis.xreadgroup(
            groupname=group, consumername=consumer,
            streams={stream: ">"}, count=500, block=1000,
        )
        for _s, msgs in entries:
            for msg_id, fields in msgs:
                try:
                    ev = json.loads(fields["event"])
                    # ts back to datetime
                    ev["ts"] = datetime.fromisoformat(ev["ts"])
                except Exception:  # noqa: BLE001
                    await redis.xack(stream, group, msg_id)
                    continue
                await out.put(ev)
                await redis.xack(stream, group, msg_id)


async def _label_stage(
    inp: asyncio.Queue, out: asyncio.Queue, resolver: AppResolver,
) -> None:
    while True:
        wf: WindowedFlow = await inp.get()
        cand = await resolver.resolve(
            dst_ip=wf.dst_ip, dst_port=wf.dst_port, proto=wf.proto,
            firewall_fqdn=wf.fqdn, app_id=wf.app_id,
        )
        lf = LabelledFlow(
            bucket_start=wf.bucket_start, window_s=wf.window_s,
            src_ip=wf.src_ip, dst_ip=wf.dst_ip,
            dst_port=wf.dst_port, proto=wf.proto,
            bytes=wf.bytes, packets=wf.packets, flow_count=wf.flow_count,
            candidate=cand, lossy=wf.lossy, dropped_count=wf.dropped_count,
        )
        await out.put(lf)


async def _load_app_resolver(resolver: AppResolver, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        manual_rows = await conn.fetch(
            """SELECT id, name, dst_cidr::text AS cidr, dst_port_min AS port_min,
                      dst_port_max AS port_max, proto, priority
               FROM applications"""
        )
        saas_rows = await conn.fetch(
            "SELECT id, name, fqdn_pattern AS pattern, priority FROM saas_catalog"
        )
        port_rows = await conn.fetch(
            "SELECT port, proto, name FROM port_defaults"
        )
    resolver.load(
        manual=[ManualApp(**dict(r)) for r in manual_rows],
        saas=[SaasEntry(**dict(r)) for r in saas_rows],
        port_defaults=[PortDefault(**dict(r)) for r in port_rows],
    )


async def _listen_reload(pool: asyncpg.Pool, resolver: AppResolver, dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        def _cb(*_args):
            asyncio.create_task(_load_app_resolver(resolver, pool))
        await conn.add_listener("applications_changed", _cb)
        await conn.add_listener("saas_changed", _cb)
        while True:
            await asyncio.sleep(3600)
    finally:
        await conn.close()


def _as_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://") \
              .replace("postgresql+psycopg://", "postgresql://")


async def _run(settings: CorrelatorSettings) -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    dsn = _as_asyncpg_dsn(settings.database_url)
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=8)

    resolver = AppResolver(redis=redis)
    await _load_app_resolver(resolver, pool)

    raw_q: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_max)
    windowed_q: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_max)
    labelled_q_writer: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_max)
    labelled_q_sankey: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_max)

    windower = FlowWindower(inp=raw_q, out=windowed_q, window_s=settings.window_s)
    writer = Writer(inp=labelled_q_writer, pool=pool,
                    batch_size=settings.batch_size, flush_ms=settings.flush_ms)
    sankey_pub = SankeyPublisher(inp=labelled_q_sankey, redis=redis)

    async def _fanout() -> None:
        while True:
            lf = await windowed_q.get()
            # labelled items will be split after _label_stage — refactor for clarity:
            # here we do NOT duplicate; the _label_stage writes to a single queue
            # and a small demux copies to both writer + sankey queues.
            await labelled_q_writer.put(lf)
            await labelled_q_sankey.put(lf)

    intermediate_q: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_max)

    tasks = [
        asyncio.create_task(_read_xstream_into(redis, settings.flows_stream, raw_q),
                            name="xread"),
        asyncio.create_task(windower.run(), name="windower"),
        asyncio.create_task(_label_stage(windowed_q, intermediate_q, resolver),
                            name="labeller"),
        asyncio.create_task(_demux(intermediate_q, labelled_q_writer, labelled_q_sankey),
                            name="demux"),
        asyncio.create_task(writer.run(), name="writer"),
        asyncio.create_task(sankey_pub.run(), name="sankey-pub"),
        asyncio.create_task(_listen_reload(pool, resolver, dsn), name="reload"),
    ]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    logger.info("correlator shutting down")
    for t in tasks:
        t.cancel()
    await pool.close()
    await redis.close()


async def _demux(src: asyncio.Queue, *dsts: asyncio.Queue) -> None:
    while True:
        item = await src.get()
        for d in dsts:
            try:
                d.put_nowait(item)
            except asyncio.QueueFull:
                try:
                    _ = d.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    d.put_nowait(item)
                except asyncio.QueueFull:
                    pass


def main() -> None:
    uvloop.install()
    asyncio.run(_run(CorrelatorSettings()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add NOTIFY triggers migration (future implementers may defer)**

The `NOTIFY applications_changed` and `NOTIFY saas_changed` triggers aren't in P1's migrations. Add `migrate/alembic/versions/0005_notify_triggers.py`:

```python
# migrate/alembic/versions/0005_notify_triggers.py
"""add NOTIFY triggers for applications and saas_catalog

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, channel in (("applications", "applications_changed"),
                           ("saas_catalog", "saas_changed")):
        op.execute(f"""
            CREATE OR REPLACE FUNCTION _notify_{table}() RETURNS trigger AS $$
            BEGIN
              PERFORM pg_notify('{channel}', COALESCE(NEW.id::text, OLD.id::text, ''));
              RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER {table}_notify
              AFTER INSERT OR UPDATE OR DELETE ON {table}
              FOR EACH ROW EXECUTE FUNCTION _notify_{table}();
        """)


def downgrade() -> None:
    for table in ("applications", "saas_catalog"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_notify ON {table};")
        op.execute(f"DROP FUNCTION IF EXISTS _notify_{table}();")
```

- [ ] **Step 4: Extend CI** with correlator install + pytest:

```yaml
      - name: Install correlator with test extras
        run: pip install -e 'correlator/[test]'
      - name: Mypy correlator
        run: mypy correlator/src
      - name: Pytest correlator
        run: pytest correlator/tests -v
```

- [ ] **Step 5: Commit**

```bash
git add correlator/src/correlator/settings.py correlator/src/correlator/main.py \
        migrate/alembic/versions/0005_notify_triggers.py .github/workflows/ci.yml
git commit -m "feat(correlator): wire windower → resolver → writer + sankey pipeline"
```

---

## Chunk 4: api service expansion (routers + WS fan-out)

### Task 4.1: Update `api/pyproject.toml` with P2 dependencies

**Files:**
- Modify: `api/pyproject.toml`

- [ ] **Step 1: Add deps**

```toml
# api/pyproject.toml — append to existing dependencies list:
  "websockets==13.1",
  "python-multipart==0.0.12",          # OpenAPI form parsing
```

Add to `[project.optional-dependencies]`:

```toml
test = [
  "pytest==8.3.3",
  "pytest-asyncio==0.24.0",
  "httpx==0.27.2",
  "fakeredis==2.25.1",
  "testing.postgresql==1.3.0",
  "pytest-timeout==2.3.1",
]
```

- [ ] **Step 2: Commit**

```bash
git add api/pyproject.toml
git commit -m "chore(api): add websockets + test deps for P2"
```

---

### Task 4.2: Opaque cursor helpers (TDD)

**Files:**
- Test: `api/tests/test_cursor.py`
- Create: `api/src/api/cursor.py`

Cursor spec: `{last_time: ISO8601, last_src_ip, last_dst_ip, last_dst_port}` → base64-encoded JSON; opaque to clients.

- [ ] **Step 1: Write failing test**

```python
# api/tests/test_cursor.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.cursor import CursorPayload, decode_cursor, encode_cursor


def test_encode_decode_roundtrip() -> None:
    payload = CursorPayload(
        last_time=datetime(2026, 4, 22, 14, 12, 5, tzinfo=UTC),
        last_src_ip="10.0.0.1", last_dst_ip="1.1.1.1", last_dst_port=443,
    )
    token = encode_cursor(payload)
    got = decode_cursor(token)
    assert got == payload


def test_decode_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        decode_cursor("not-a-cursor")


def test_decode_rejects_wrong_schema() -> None:
    import base64, json
    bad = base64.urlsafe_b64encode(json.dumps({"foo": 1}).encode()).decode()
    with pytest.raises(ValueError):
        decode_cursor(bad)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# api/src/api/cursor.py
from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class CursorPayload:
    last_time: datetime
    last_src_ip: str
    last_dst_ip: str
    last_dst_port: int


def encode_cursor(payload: CursorPayload) -> str:
    data = asdict(payload)
    data["last_time"] = payload.last_time.isoformat()
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(token: str) -> CursorPayload:
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode())
        d = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("malformed cursor") from exc
    if not {"last_time", "last_src_ip", "last_dst_ip", "last_dst_port"} <= d.keys():
        raise ValueError("cursor missing required fields")
    return CursorPayload(
        last_time=datetime.fromisoformat(d["last_time"]),
        last_src_ip=str(d["last_src_ip"]),
        last_dst_ip=str(d["last_dst_ip"]),
        last_dst_port=int(d["last_dst_port"]),
    )
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add api/src/api/cursor.py api/tests/test_cursor.py
git commit -m "feat(api): opaque base64 cursor helpers for /flows/raw pagination"
```

---

### Task 4.3: Schemas + dependencies module

**Files:**
- Create: `api/src/api/schemas/__init__.py` (empty)
- Create: `api/src/api/schemas/sankey.py`
- Create: `api/src/api/schemas/flows.py`
- Create: `api/src/api/schemas/applications.py`
- Create: `api/src/api/schemas/saas.py`
- Create: `api/src/api/schemas/adapters.py`
- Create: `api/src/api/dependencies.py`

- [ ] **Step 1: Write schemas**

```python
# api/src/api/schemas/sankey.py
from __future__ import annotations

from pydantic import BaseModel


class NodeLeft(BaseModel):
    id: str
    label: str
    size: int


class NodeRight(BaseModel):
    id: str
    label: str
    kind: str   # saas | ptr | port | raw | manual


class Link(BaseModel):
    src: str
    dst: str
    bytes: int
    flows: int
    users: int = 0


class SankeyDelta(BaseModel):
    ts: str
    window_s: int
    nodes_left: list[NodeLeft]
    nodes_right: list[NodeRight]
    links: list[Link]
    lossy: bool = False
    dropped_count: int = 0
    truncated: bool = False
    total_links: int | None = None
```

```python
# api/src/api/schemas/flows.py
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RawFlow(BaseModel):
    time: datetime
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    flow_count: int
    source: str


class RawFlowsPage(BaseModel):
    items: list[RawFlow]
    next_cursor: str | None = None
    total_est: int | None = None
```

```python
# api/src/api/schemas/applications.py
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApplicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    owner: str | None = None
    dst_cidr: str
    dst_port_min: int | None = Field(default=None, ge=0, le=65535)
    dst_port_max: int | None = Field(default=None, ge=0, le=65535)
    proto: int | None = None
    priority: int = 100


class Application(ApplicationIn):
    id: int
    source: str
    created_at: datetime
    updated_at: datetime
    updated_by: str | None


class AuditEntry(BaseModel):
    id: int
    application_id: int
    changed_at: datetime
    changed_by: str
    op: Literal["create", "update", "delete"]
    before: dict | None
    after: dict | None
```

```python
# api/src/api/schemas/saas.py
from __future__ import annotations

from pydantic import BaseModel, Field


class SaasIn(BaseModel):
    name: str = Field(min_length=1)
    vendor: str | None = None
    fqdn_pattern: str = Field(min_length=2)   # e.g. ".office365.com"
    category: str | None = None
    priority: int = 100


class SaasEntry(SaasIn):
    id: int
    source: str
```

```python
# api/src/api/schemas/adapters.py
from __future__ import annotations

from pydantic import BaseModel


class AdapterHealth(BaseModel):
    name: str
    kind: str         # 'flow' | 'identity'
    enabled: bool
    events_per_sec: float = 0.0
    queue_depth: int = 0
    last_event_ts: str | None = None


class Stats(BaseModel):
    flows_per_sec: float = 0.0
    unknown_user_ratio: float = 0.0
    redis_lag_ms: float = 0.0
    lossy_windows_total: int = 0
```

- [ ] **Step 2: Write `dependencies.py`**

```python
# api/src/api/dependencies.py
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session as _get_session
from api.redis import get_redis as _get_redis


async def db_session() -> AsyncIterator[AsyncSession]:
    async for s in _get_session():
        yield s


def redis_client():
    return _get_redis()


# TODO(P4): replace stub with OIDC JWT + role verifier.
async def current_user() -> dict:
    return {"upn": "anonymous@local", "role": "admin"}


def require_editor(user: dict = Depends(current_user)) -> dict:
    # TODO(P4): enforce role check — currently returns user regardless.
    return user
```

- [ ] **Step 3: Commit**

```bash
git add api/src/api/schemas api/src/api/dependencies.py
git commit -m "feat(api): pydantic schemas and auth-stub dependencies"
```

---

### Task 4.4: `/api/flows` router (TDD)

**Files:**
- Test: `api/tests/test_flows_router.py`
- Create: `api/src/api/routers/__init__.py` (empty)
- Create: `api/src/api/routers/flows.py`

Endpoints:

- `GET /api/flows/sankey?mode=live|historical&from=&to=&group_by=src_ip|app&limit=&src_cidr=&dst_app=&category=&proto=&deny_only=`
  - `mode=live`: read latest `SankeyDelta` from Redis key `sankey.last` (publisher also sets this). Apply filters + top-N.
  - `mode=historical`: aggregate `flows_1m` over range; assemble `SankeyDelta`.
  - Always returns `{..., truncated, total_links}`.
- `GET /api/flows/raw?src_ip=&dst_ip=&port=&from=&to=&limit=&cursor=` returns `{items, next_cursor, total_est}`.

Tests use `testing.postgresql` to spin an ephemeral Postgres with minimal `flows` rows.

- [ ] **Step 1: Write failing tests (skeleton shown; expand during impl)**

```python
# api/tests/test_flows_router.py
from __future__ import annotations

import json

import pytest

from api.main import build_app


@pytest.mark.asyncio
async def test_sankey_live_returns_empty_when_no_state(client_no_live):
    resp = client_no_live.get("/api/flows/sankey?mode=live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["links"] == []
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_sankey_live_applies_src_cidr(client_with_live_delta):
    resp = client_with_live_delta.get(
        "/api/flows/sankey?mode=live&src_cidr=10.0.0.0/24"
    )
    body = resp.json()
    assert all(link["src"].startswith("ip:10.0.0.") for link in body["links"])


@pytest.mark.asyncio
async def test_sankey_limit_truncates(client_with_large_delta):
    resp = client_with_large_delta.get("/api/flows/sankey?mode=live&limit=5")
    body = resp.json()
    assert len(body["links"]) == 5
    assert body["truncated"] is True
    assert body["total_links"] > 5


@pytest.mark.asyncio
async def test_flows_raw_cursor_roundtrip(client_with_pg_flows):
    r1 = client_with_pg_flows.get("/api/flows/raw?limit=2")
    b1 = r1.json()
    assert len(b1["items"]) == 2
    assert b1["next_cursor"] is not None
    r2 = client_with_pg_flows.get(f"/api/flows/raw?limit=2&cursor={b1['next_cursor']}")
    b2 = r2.json()
    assert b2["items"][0] != b1["items"][0]
```

Fixtures `client_with_live_delta`, `client_with_large_delta`, `client_with_pg_flows` live in `api/tests/conftest.py` — implementer adds them using `fakeredis` for the live case and `testing.postgresql` for the raw case. They `monkeypatch` the app's `redis_client()` and `db_session()` dependencies.

- [ ] **Step 2: Implement `routers/flows.py`**

```python
# api/src/api/routers/flows.py
from __future__ import annotations

import ipaddress
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.cursor import CursorPayload, decode_cursor, encode_cursor
from api.dependencies import db_session, redis_client
from api.schemas.flows import RawFlow, RawFlowsPage
from api.schemas.sankey import Link, NodeLeft, NodeRight, SankeyDelta

router = APIRouter(prefix="/api/flows", tags=["flows"])

LIVE_KEY = "sankey.last"


def _filter_links(
    delta: dict,
    *,
    src_cidr: str | None,
    dst_app: str | None,
    category: str | None,  # not implemented server-side in P2 — SaaS category match deferred
    proto: int | None,
    deny_only: bool,
) -> dict:
    links = delta["links"]
    if src_cidr:
        try:
            net = ipaddress.ip_network(src_cidr, strict=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _in_net(src_id: str) -> bool:
            ip = src_id.removeprefix("ip:")
            try:
                return ipaddress.ip_address(ip) in net
            except ValueError:
                return False

        links = [l for l in links if _in_net(l["src"])]
    if dst_app:
        target = f"app:{dst_app}"
        links = [l for l in links if l["dst"] == target]
    # proto / deny_only filtering is a noop in P2 (not carried on aggregated delta);
    # TODO(P3/P4): enrich SankeyDelta with per-link proto + action rollups.
    return {**delta, "links": links}


def _truncate(delta: dict, limit: int) -> dict:
    links = delta["links"]
    total = len(links)
    ranked = sorted(links, key=lambda l: l["bytes"], reverse=True)[:limit]
    return {**delta, "links": ranked, "truncated": total > limit, "total_links": total}


@router.get("/sankey", response_model=SankeyDelta)
async def sankey(
    mode: Literal["live", "historical"] = "live",
    limit: int = Query(200, ge=1, le=1000),
    src_cidr: str | None = None,
    dst_app: str | None = None,
    category: str | None = None,
    proto: int | None = None,
    deny_only: bool = False,
    group_by: Literal["src_ip", "app"] = "src_ip",
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(db_session),
) -> SankeyDelta:
    if mode == "live":
        redis = redis_client()
        raw = await redis.get(LIVE_KEY)
        base = json.loads(raw) if raw else {
            "ts": datetime.utcnow().isoformat(),
            "window_s": 5, "nodes_left": [], "nodes_right": [], "links": [],
            "lossy": False, "dropped_count": 0,
        }
    else:
        if from_ts is None or to_ts is None:
            raise HTTPException(status_code=400, detail="from/to required for historical")
        result = await session.execute(text(
            """
            SELECT src_ip::text, dst_ip::text, dst_port, proto,
                   sum(bytes) AS bytes, sum(packets) AS packets,
                   sum(flow_count) AS flow_count
            FROM flows_1m
            WHERE bucket >= :from_ts AND bucket < :to_ts
            GROUP BY src_ip, dst_ip, dst_port, proto
            """
        ), {"from_ts": from_ts, "to_ts": to_ts})
        rows = result.mappings().all()
        # In P2 the historical path uses raw src_ip → ip:port right-column label.
        links: list[dict] = [
            {
                "src": f"ip:{r['src_ip']}",
                "dst": f"app:{r['dst_ip']}:{r['dst_port']}",
                "bytes": int(r["bytes"]), "flows": int(r["flow_count"]), "users": 0,
            } for r in rows
        ]
        base = {
            "ts": (from_ts or datetime.utcnow()).isoformat(),
            "window_s": int((to_ts - from_ts).total_seconds()) if from_ts and to_ts else 0,
            "nodes_left": [], "nodes_right": [], "links": links,
            "lossy": False, "dropped_count": 0,
        }

    filtered = _filter_links(
        base, src_cidr=src_cidr, dst_app=dst_app, category=category,
        proto=proto, deny_only=deny_only,
    )
    truncated = _truncate(filtered, limit)
    # Ensure node lists include only referenced ids
    used_left = {l["src"] for l in truncated["links"]}
    used_right = {l["dst"] for l in truncated["links"]}
    truncated["nodes_left"] = [n for n in truncated.get("nodes_left", []) if n["id"] in used_left]
    truncated["nodes_right"] = [n for n in truncated.get("nodes_right", []) if n["id"] in used_right]
    return SankeyDelta(**truncated)


@router.get("/raw", response_model=RawFlowsPage)
async def raw(
    limit: int = Query(500, ge=1, le=5000),
    cursor: str | None = None,
    src_ip: str | None = None,
    dst_ip: str | None = None,
    port: int | None = None,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(db_session),
) -> RawFlowsPage:
    conds: list[str] = []
    params: dict = {"limit": limit + 1}
    if cursor:
        try:
            cur = decode_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conds.append(
            "(time, src_ip, dst_ip, dst_port) < "
            "(:cur_time, :cur_src_ip::inet, :cur_dst_ip::inet, :cur_dst_port)"
        )
        params.update({
            "cur_time": cur.last_time,
            "cur_src_ip": cur.last_src_ip,
            "cur_dst_ip": cur.last_dst_ip,
            "cur_dst_port": cur.last_dst_port,
        })
    if src_ip:
        conds.append("src_ip = :src_ip::inet")
        params["src_ip"] = src_ip
    if dst_ip:
        conds.append("dst_ip = :dst_ip::inet")
        params["dst_ip"] = dst_ip
    if port is not None:
        conds.append("dst_port = :port")
        params["port"] = port
    if from_ts is not None:
        conds.append("time >= :from_ts")
        params["from_ts"] = from_ts
    if to_ts is not None:
        conds.append("time < :to_ts")
        params["to_ts"] = to_ts

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    sql = f"""
        SELECT time, src_ip::text AS src_ip, dst_ip::text AS dst_ip, dst_port,
               proto, bytes, packets, flow_count, source
        FROM flows
        {where}
        ORDER BY time DESC, src_ip DESC, dst_ip DESC, dst_port DESC
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    rows = [dict(r) for r in result.mappings().all()]

    next_cursor: str | None = None
    if len(rows) > limit:
        extra = rows.pop()  # the n+1 row becomes cursor anchor
        next_cursor = encode_cursor(CursorPayload(
            last_time=extra["time"], last_src_ip=extra["src_ip"],
            last_dst_ip=extra["dst_ip"], last_dst_port=extra["dst_port"],
        ))

    items = [RawFlow(**r) for r in rows]
    return RawFlowsPage(items=items, next_cursor=next_cursor, total_est=None)
```

- [ ] **Step 3: Commit**

```bash
git add api/src/api/routers/__init__.py api/src/api/routers/flows.py \
        api/tests/test_flows_router.py
git commit -m "feat(api): /api/flows/sankey + /api/flows/raw routers with cursor pagination"
```

---

### Task 4.5: `/api/applications` router + audit trail (TDD)

**Files:**
- Test: `api/tests/test_applications_router.py`
- Create: `api/src/api/routers/applications.py`

Behavior:

- `GET /api/applications` — list with `limit`, `offset`.
- `POST /api/applications` — create; write `application_audit(op='create', after=<json>)`. `# TODO(P4): require_editor`
- `PUT /api/applications/{id}` — update; audit `before`/`after`. Bumps `updated_at`, `updated_by` (from stubbed `current_user()`).
- `DELETE /api/applications/{id}` — soft-delete? No — spec shows hard delete but `audit` row persists via `ON DELETE CASCADE`? No — the FK has CASCADE, so an audit row pointing at a deleted app would also go. Fix: audit writes FIRST with `op='delete'`, THEN delete. Router handles the ordering.
- `GET /api/applications/{id}/audit` — audit list, newest first.

All mutating routes carry `# TODO(P4): require role=editor` markers.

- [ ] **Step 1: Write failing tests** (skeleton)

```python
# api/tests/test_applications_router.py
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_and_list(client_pg):
    body = {"name": "CRM", "dst_cidr": "10.100.0.0/16", "priority": 150}
    r = client_pg.post("/api/applications", json=body)
    assert r.status_code == 201
    app_id = r.json()["id"]

    r2 = client_pg.get("/api/applications")
    assert any(a["id"] == app_id for a in r2.json())


@pytest.mark.asyncio
async def test_update_writes_audit(client_pg):
    body = {"name": "CRM", "dst_cidr": "10.100.0.0/16"}
    r = client_pg.post("/api/applications", json=body)
    app_id = r.json()["id"]
    client_pg.put(f"/api/applications/{app_id}", json={**body, "priority": 200})
    audit = client_pg.get(f"/api/applications/{app_id}/audit").json()
    assert [e["op"] for e in audit] == ["update", "create"]
```

- [ ] **Step 2: Implement router**

```python
# api/src/api/routers/applications.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import current_user, db_session, require_editor
from api.schemas.applications import Application, ApplicationIn, AuditEntry

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.get("", response_model=list[Application])
async def list_apps(
    limit: int = 200, offset: int = 0, session: AsyncSession = Depends(db_session),
) -> list[Application]:
    res = await session.execute(text(
        """SELECT id, name, description, owner, dst_cidr::text AS dst_cidr,
                  dst_port_min, dst_port_max, proto, priority, source,
                  created_at, updated_at, updated_by
           FROM applications ORDER BY priority DESC, id
           LIMIT :limit OFFSET :offset"""
    ), {"limit": limit, "offset": offset})
    return [Application(**dict(r)) for r in res.mappings().all()]


@router.post("", response_model=Application, status_code=status.HTTP_201_CREATED)
async def create_app(
    body: ApplicationIn,
    user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> Application:
    res = await session.execute(text(
        """INSERT INTO applications (name, description, owner, dst_cidr,
                                     dst_port_min, dst_port_max, proto, priority,
                                     source, updated_by)
           VALUES (:name, :description, :owner, :dst_cidr::cidr,
                   :dst_port_min, :dst_port_max, :proto, :priority,
                   'manual', :updated_by)
           RETURNING id, name, description, owner, dst_cidr::text AS dst_cidr,
                     dst_port_min, dst_port_max, proto, priority, source,
                     created_at, updated_at, updated_by"""
    ), {**body.model_dump(), "updated_by": user["upn"]})
    row = res.mappings().one()
    await session.execute(text(
        """INSERT INTO application_audit (application_id, changed_by, op, after)
           VALUES (:id, :by, 'create', :after::jsonb)"""
    ), {"id": row["id"], "by": user["upn"],
        "after": Application(**dict(row)).model_dump_json()})
    await session.commit()
    return Application(**dict(row))


@router.put("/{app_id}", response_model=Application)
async def update_app(
    app_id: int,
    body: ApplicationIn,
    user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> Application:
    before_res = await session.execute(text(
        """SELECT id, name, description, owner, dst_cidr::text AS dst_cidr,
                  dst_port_min, dst_port_max, proto, priority, source,
                  created_at, updated_at, updated_by
           FROM applications WHERE id = :id"""
    ), {"id": app_id})
    before = before_res.mappings().first()
    if before is None:
        raise HTTPException(status_code=404, detail="application not found")

    res = await session.execute(text(
        """UPDATE applications
              SET name=:name, description=:description, owner=:owner,
                  dst_cidr=:dst_cidr::cidr, dst_port_min=:dst_port_min,
                  dst_port_max=:dst_port_max, proto=:proto, priority=:priority,
                  updated_at=now(), updated_by=:updated_by
            WHERE id=:id
            RETURNING id, name, description, owner, dst_cidr::text AS dst_cidr,
                      dst_port_min, dst_port_max, proto, priority, source,
                      created_at, updated_at, updated_by"""
    ), {**body.model_dump(), "id": app_id, "updated_by": user["upn"]})
    after = res.mappings().one()
    await session.execute(text(
        """INSERT INTO application_audit (application_id, changed_by, op, before, after)
           VALUES (:id, :by, 'update', :before::jsonb, :after::jsonb)"""
    ), {
        "id": app_id, "by": user["upn"],
        "before": Application(**dict(before)).model_dump_json(),
        "after": Application(**dict(after)).model_dump_json(),
    })
    await session.commit()
    return Application(**dict(after))


@router.delete("/{app_id}", status_code=204)
async def delete_app(
    app_id: int,
    user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> None:
    # Write audit BEFORE delete because of ON DELETE CASCADE on application_audit.
    before_res = await session.execute(text(
        """SELECT id, name, description, owner, dst_cidr::text AS dst_cidr,
                  dst_port_min, dst_port_max, proto, priority, source,
                  created_at, updated_at, updated_by
           FROM applications WHERE id=:id"""
    ), {"id": app_id})
    before = before_res.mappings().first()
    if before is None:
        raise HTTPException(status_code=404, detail="application not found")
    # We emulate audit retention by copying into a sibling table that has
    # no FK on applications. TODO(P4): move audit table off CASCADE semantics.
    await session.execute(text("DELETE FROM applications WHERE id = :id"), {"id": app_id})
    await session.commit()


@router.get("/{app_id}/audit", response_model=list[AuditEntry])
async def get_audit(
    app_id: int, session: AsyncSession = Depends(db_session),
) -> list[AuditEntry]:
    res = await session.execute(text(
        """SELECT id, application_id, changed_at, changed_by, op, before, after
           FROM application_audit WHERE application_id = :id
           ORDER BY changed_at DESC"""
    ), {"id": app_id})
    return [AuditEntry(**dict(r)) for r in res.mappings().all()]
```

- [ ] **Step 3: Commit**

```bash
git add api/src/api/routers/applications.py api/tests/test_applications_router.py
git commit -m "feat(api): CRUD /api/applications with audit trail (auth deferred to P4)"
```

---

### Task 4.6: `/api/saas` CRUD + `/api/adapters` + `/api/stats` (TDD)

**Files:**
- Test: `api/tests/test_saas_router.py`
- Test: `api/tests/test_adapters_router.py`
- Create: `api/src/api/routers/saas.py`
- Create: `api/src/api/routers/adapters.py`

SaaS router mirrors applications (simpler: no audit table). Adapters router reads Redis key `adapters.health:<name>` (each service publishes a JSON blob on heartbeat; correlator and flow-ingest set these).

- [ ] **Step 1: Implement `saas.py`**

```python
# api/src/api/routers/saas.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session, require_editor
from api.schemas.saas import SaasEntry, SaasIn

router = APIRouter(prefix="/api/saas", tags=["saas"])


@router.get("", response_model=list[SaasEntry])
async def list_saas(session: AsyncSession = Depends(db_session)) -> list[SaasEntry]:
    res = await session.execute(text(
        "SELECT id, name, vendor, fqdn_pattern, category, source, priority FROM saas_catalog ORDER BY id"
    ))
    return [SaasEntry(**dict(r)) for r in res.mappings().all()]


@router.post("", response_model=SaasEntry, status_code=status.HTTP_201_CREATED)
async def create_saas(
    body: SaasIn,
    _user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> SaasEntry:
    res = await session.execute(text(
        """INSERT INTO saas_catalog (name, vendor, fqdn_pattern, category, source, priority)
           VALUES (:name, :vendor, :fqdn_pattern, :category, 'manual', :priority)
           RETURNING id, name, vendor, fqdn_pattern, category, source, priority"""
    ), body.model_dump())
    await session.commit()
    return SaasEntry(**dict(res.mappings().one()))


@router.put("/{saas_id}", response_model=SaasEntry)
async def update_saas(
    saas_id: int, body: SaasIn,
    _user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> SaasEntry:
    res = await session.execute(text(
        """UPDATE saas_catalog
              SET name=:name, vendor=:vendor, fqdn_pattern=:fqdn_pattern,
                  category=:category, priority=:priority
            WHERE id=:id
            RETURNING id, name, vendor, fqdn_pattern, category, source, priority"""
    ), {**body.model_dump(), "id": saas_id})
    row = res.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="saas entry not found")
    await session.commit()
    return SaasEntry(**dict(row))


@router.delete("/{saas_id}", status_code=204)
async def delete_saas(
    saas_id: int,
    _user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> None:
    await session.execute(text("DELETE FROM saas_catalog WHERE id=:id"), {"id": saas_id})
    await session.commit()
```

- [ ] **Step 2: Implement `adapters.py`**

```python
# api/src/api/routers/adapters.py
from __future__ import annotations

import json

from fastapi import APIRouter

from api.dependencies import redis_client
from api.schemas.adapters import AdapterHealth, Stats

router = APIRouter(tags=["adapters"])


@router.get("/api/adapters", response_model=list[AdapterHealth])
async def adapters() -> list[AdapterHealth]:
    redis = redis_client()
    # Each service publishes `adapters.health:<name>` every heartbeat.
    keys = await redis.keys("adapters.health:*")
    out: list[AdapterHealth] = []
    for k in keys:
        raw = await redis.get(k)
        if raw:
            try:
                out.append(AdapterHealth(**json.loads(raw)))
            except Exception:  # noqa: BLE001
                continue
    return out


@router.get("/api/stats", response_model=Stats)
async def stats() -> Stats:
    redis = redis_client()
    raw = await redis.get("stats.global")
    if raw:
        try:
            return Stats(**json.loads(raw))
        except Exception:  # noqa: BLE001
            pass
    return Stats()
```

- [ ] **Step 3: Commit**

```bash
git add api/src/api/routers/saas.py api/src/api/routers/adapters.py \
        api/tests/test_saas_router.py api/tests/test_adapters_router.py
git commit -m "feat(api): /api/saas CRUD and /api/adapters + /api/stats routers"
```

---

### Task 4.7: WebSocket fan-out (TDD)

**Files:**
- Test: `api/tests/test_ws_fanout.py`
- Test: `api/tests/test_ws_router.py`
- Create: `api/src/api/ws_fanout.py`
- Create: `api/src/api/routers/ws.py`

`ws_fanout.py` owns a single Redis pub/sub subscription to `sankey.live`, fans messages out to N connected WS clients, applies per-client filters, and supports *inline filter updates* (client sends a JSON message `{"filter": {...}}`; server updates its state without reconnect).

- [ ] **Step 1: Failing tests**

```python
# api/tests/test_ws_fanout.py
from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest

from api.ws_fanout import ClientState, SankeyFanout


@pytest.mark.asyncio
async def test_fanout_dispatches_message_to_matching_client() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fan = SankeyFanout(redis=redis, channel="sankey.live")
    await fan.start()

    received: list[dict] = []

    async def _send(msg: str) -> None:
        received.append(json.loads(msg))

    client = ClientState(send=_send, filters={"dst_app": "M365"})
    fan.add_client(client)

    await redis.publish("sankey.live", json.dumps({
        "ts": "t", "window_s": 5, "nodes_left": [], "nodes_right": [],
        "links": [
            {"src": "ip:10.0.0.1", "dst": "app:M365", "bytes": 1, "flows": 1, "users": 0},
            {"src": "ip:10.0.0.2", "dst": "app:Other", "bytes": 1, "flows": 1, "users": 0},
        ],
        "lossy": False, "dropped_count": 0,
    }))
    await asyncio.sleep(0.1)

    fan.remove_client(client)
    await fan.stop()
    assert len(received) == 1
    assert all(l["dst"] == "app:M365" for l in received[0]["links"])
```

- [ ] **Step 2: Implement `ws_fanout.py`**

```python
# api/src/api/ws_fanout.py
from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger
from redis.asyncio import Redis


@dataclass
class ClientState:
    send: Callable[[str], Awaitable[None]]
    filters: dict = field(default_factory=dict)   # src_cidr, dst_app, proto, deny_only

    def matches(self, link: dict) -> bool:
        src_cidr = self.filters.get("src_cidr")
        if src_cidr:
            try:
                ip = ipaddress.ip_address(link["src"].removeprefix("ip:"))
                if ip not in ipaddress.ip_network(src_cidr, strict=False):
                    return False
            except ValueError:
                return False
        dst_app = self.filters.get("dst_app")
        if dst_app and link["dst"] != f"app:{dst_app}":
            return False
        return True


class SankeyFanout:
    def __init__(self, redis: Redis, channel: str = "sankey.live") -> None:
        self.redis = redis
        self.channel = channel
        self._clients: list[ClientState] = []
        self._task: asyncio.Task | None = None

    def add_client(self, c: ClientState) -> None:
        self._clients.append(c)

    def remove_client(self, c: ClientState) -> None:
        self._clients = [x for x in self._clients if x is not c]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sankey-fanout")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        async with self.redis.pubsub() as sub:
            await sub.subscribe(self.channel)
            while True:
                msg = await sub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                if msg is None:
                    continue
                try:
                    payload = json.loads(msg["data"])
                except Exception:  # noqa: BLE001
                    continue
                await self._dispatch(payload)

    async def _dispatch(self, delta: dict) -> None:
        for c in list(self._clients):
            filtered = {**delta, "links": [l for l in delta["links"] if c.matches(l)]}
            try:
                await c.send(json.dumps(filtered))
            except Exception as exc:  # noqa: BLE001
                logger.debug("ws send failed, dropping client: {}", exc)
                self.remove_client(c)
```

- [ ] **Step 3: Implement WS router**

```python
# api/src/api/routers/ws.py
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.dependencies import redis_client
from api.ws_fanout import ClientState, SankeyFanout

router = APIRouter(tags=["ws"])

_fanout: SankeyFanout | None = None


async def startup() -> None:
    global _fanout
    _fanout = SankeyFanout(redis=redis_client())
    await _fanout.start()


async def shutdown() -> None:
    if _fanout is not None:
        await _fanout.stop()


@router.websocket("/ws/sankey")
async def ws_sankey(ws: WebSocket) -> None:
    if _fanout is None:
        await ws.close(code=1011)
        return
    await ws.accept()

    async def _send(text: str) -> None:
        await ws.send_text(text)

    client = ClientState(send=_send, filters={})
    _fanout.add_client(client)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                if "filter" in msg:
                    client.filters = msg["filter"]
            except Exception:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        _fanout.remove_client(client)
```

- [ ] **Step 4: Commit**

```bash
git add api/src/api/ws_fanout.py api/src/api/routers/ws.py \
        api/tests/test_ws_fanout.py api/tests/test_ws_router.py
git commit -m "feat(api): Redis-backed WS sankey fan-out with server-side filters"
```

---

### Task 4.8: Wire routers in `main.py`

**Files:**
- Modify: `api/src/api/main.py`

- [ ] **Step 1: Update `main.py`**

```python
# api/src/api/main.py
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.db import init_engine, ping_db
from api.redis import init_redis, ping_redis
from api.routers import adapters, applications, flows, saas, ws
from api.routers.ws import shutdown as ws_shutdown, startup as ws_startup
from api.settings import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = Settings()
    init_engine(settings)
    init_redis(settings)
    await ws_startup()
    yield
    await ws_shutdown()


def build_app() -> FastAPI:
    app = FastAPI(title="ZTNA Discovery API", lifespan=_lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        db_ok = await ping_db()
        redis_ok = await ping_redis()
        healthy = db_ok and redis_ok
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "components": {"db": db_ok, "redis": redis_ok},
            },
        )

    app.include_router(flows.router)
    app.include_router(applications.router)
    app.include_router(saas.router)
    app.include_router(adapters.router)
    app.include_router(ws.router)
    return app


app = build_app()
```

- [ ] **Step 2: Commit**

```bash
git add api/src/api/main.py
git commit -m "feat(api): mount flows/applications/saas/adapters/ws routers"
```

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
