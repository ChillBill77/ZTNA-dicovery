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
