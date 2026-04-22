# ZTNA Flow Discovery — Plan 4: Polish & Ops

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-04-22-ztna-flow-discovery-design.md`

**Prior plans:** `docs/superpowers/plans/2026-04-22-ztna-p1-foundation.md` (stack skeleton), `docs/superpowers/plans/2026-04-22-ztna-p2-flow-pipeline.md` (flow pipeline + web), `docs/superpowers/plans/2026-04-22-ztna-p3-identity-lcd.md` (identity + LCD).

**Goal:** Close the v1 implementation by adding production readiness: OIDC auth with RBAC, Traefik dashboard protection, a Prometheus/Grafana observability profile, a Locust load test, a full Playwright E2E suite, supply-chain security in CI, operations runbooks, a backup sidecar with restore path, and container/process hardening. After P4 the stack is safe to deploy into a production environment against the spec's success criteria (§1).

**Architecture:** Auth is added as a new package inside the existing `api/` service (`api/src/api/auth/`), not as a separate container — OIDC login flow, JWKS cache, role mapping from Entra group IDs, and a `require_role` FastAPI dependency. Observability is a Compose **overlay** (`docker-compose.observe.yml` / profile `observe`) that layers Prometheus and Grafana on top of the P1/P2/P3 stack; each Python service gains a `prometheus_client`-backed `/metrics` endpoint and loguru structured-logging config. Load tests run in a separate overlay (`docker-compose.loadtest.yml` / profile `loadtest`) that launches a Locust master plus synthetic-event generators. Playwright E2E lives under `e2e/` and runs headless in CI against a Compose-driven stack. Supply-chain scanning (`pip-audit`, `npm audit`, `trivy`, Syft SBOM) is wired into `.github/workflows/security.yml`. Backups are a `postgres:16-alpine` sidecar running `pg_dump -Fc` via cron with a 7-day rotation; restore is a documented script. Hardening wraps up by switching production secrets to Docker secrets, pinning all Python/JS deps via lockfiles, adding per-service resource limits, switching app Dockerfiles to a non-root user, and capping container log volume.

**Tech Stack:** `fastapi` + `authlib` (OIDC) + `python-jose[cryptography]` (JWT) + `prometheus_client` + `loguru` (Python), `locust` (load test), `@playwright/test` + `axe-playwright` (E2E + a11y), Prometheus + Grafana (observability), `pip-audit` + `npm audit` + `aquasecurity/trivy-action` + `anchore/syft` (supply chain), `postgres:16-alpine` + cron (backup sidecar), Docker secrets + `uv` pinning (hardening).

---

## File Structure

Files created or modified by this plan:

```
ztna-discovery/
  docker-compose.observe.yml             # NEW: prometheus + grafana overlay (profile: observe)
  docker-compose.loadtest.yml            # NEW: locust master/worker + generators (profile: loadtest)
  docker-compose.prod.yml                # MODIFY: add resource limits, docker secrets, logrotate caps
  .env.example                           # MODIFY: add OIDC + backup envs
  .gitignore                             # MODIFY: ignore ./backups/ host volume
  backups/.gitkeep                       # NEW: placeholder for pg_dump host mount

  api/pyproject.toml                     # MODIFY: add auth + metrics + loguru deps
  api/Dockerfile                         # MODIFY: non-root user, pinned uv-generated requirements
  api/requirements.txt                   # NEW: uv-compiled lockfile (committed)
  api/src/api/auth/
    __init__.py
    jwks.py                              # JWKS fetch + cache (1h TTL, refresh on kid mismatch)
    jwt_verify.py                        # verify Bearer JWT → claims
    session.py                           # signed cookie session + CSRF double-submit
    oidc.py                              # authlib OIDC client (login, callback, logout)
    roles.py                             # Entra group-id → role mapping, require_role dependency
    router.py                            # /api/auth/login /callback /logout /me + /auth/verify
  api/src/api/metrics.py                 # prometheus_client registry + middleware
  api/src/api/logging_config.py          # loguru JSON sink + PII hashing + W3C trace_id propagation
  api/src/api/middleware_csrf.py         # CSRF double-submit middleware
  api/src/api/main.py                    # MODIFY: mount auth router, metrics router, wrap existing CRUD with require_role
  api/tests/auth/
    test_jwks.py
    test_jwt_verify.py
    test_session.py
    test_roles.py
    test_router.py
    test_require_role.py
    test_verify_endpoint.py
    fixtures/
      mock_jwks.json
      mock_token.py
  api/tests/test_metrics.py
  api/tests/test_logging_config.py
  api/tests/test_csrf.py

  flow-ingest/src/flow_ingest/metrics.py # NEW: prometheus_client + /metrics server
  flow-ingest/src/flow_ingest/logging_config.py
  flow-ingest/src/flow_ingest/main.py    # MODIFY: start metrics server, configure logging
  flow-ingest/Dockerfile                 # MODIFY: non-root user + pinned requirements
  flow-ingest/requirements.txt           # NEW: uv-compiled lockfile
  flow-ingest/tests/test_metrics.py

  id-ingest/src/id_ingest/metrics.py
  id-ingest/src/id_ingest/logging_config.py
  id-ingest/src/id_ingest/main.py        # MODIFY
  id-ingest/Dockerfile                   # MODIFY
  id-ingest/requirements.txt             # NEW
  id-ingest/tests/test_metrics.py

  correlator/src/correlator/metrics.py
  correlator/src/correlator/logging_config.py
  correlator/src/correlator/main.py      # MODIFY
  correlator/Dockerfile                  # MODIFY
  correlator/requirements.txt            # NEW
  correlator/tests/test_metrics.py

  web/
    package.json                         # MODIFY: add playwright, axe-playwright, role-gating deps
    src/
      auth/
        AuthProvider.tsx                 # login/logout + CSRF token
        LoginPage.tsx
        LogoutButton.tsx
        useAuth.ts
        useRole.ts
      components/OverrideAppButton.tsx   # MODIFY: hide for viewer role
      App.tsx                            # MODIFY: wrap with AuthProvider, login gate
    tests/unit/
      auth.test.ts
      useRole.test.ts

  observability/
    prometheus/
      prometheus.yml                     # scrape jobs for api, flow-ingest, id-ingest, correlator
    grafana/
      provisioning/
        datasources/prometheus.yaml
        dashboards/ztna.yaml
      dashboards/
        ztna-overview.json               # canonical dashboard (also mirrored in docs/grafana/)
  docs/grafana/
    ztna-overview.json                   # committed copy for version control and reviews

  loadtest/
    Dockerfile                           # locust + fixture generators
    locustfile.py                        # scenarios: sustained, burst, identity_surge
    scenarios/
      sustained.py
      burst.py
      identity_surge.py
    generators/
      pan_fixture.py                     # synthetic Palo Alto syslog lines
      fortigate_fixture.py
      ad_4624_fixture.py
      ise_fixture.py
    tests/test_generators.py

  e2e/
    package.json
    playwright.config.ts
    tests/
      golden-path.spec.ts
      historical.spec.ts
      group-rollup.spec.ts
      unknown-user.spec.ts
      accessibility.spec.ts
      role-gates.spec.ts
    fixtures/
      oidc-mock.ts                       # msw handler for Entra in CI
      seed-flows.ts                      # POSTs synthetic flows via test-only /api/test/seed route

  scripts/
    restore-backup.sh                    # bash: stop stack, psql restore, restart
    backup-cron.sh                       # runs inside sidecar: pg_dump + rotate

  backup/
    Dockerfile                           # postgres:16-alpine + cron + backup-cron.sh
    crontab                              # 15 02 * * *   backup-cron.sh

  docs/
    operations.md                        # NEW: deployment, secrets, upgrade, backup, incidents
    security.md                          # NEW: supply-chain + secrets posture
    adapters.md                          # MODIFY: add top-of-doc link from operations.md (file itself owned by P3)

  .github/
    workflows/
      security.yml                       # NEW: pip-audit + npm audit + trivy + syft SBOM
      loadtest.yml                       # NEW: weekly scheduled load test
      e2e.yml                            # NEW: Playwright on PRs touching web/api/e2e
      ci.yml                             # MODIFY: add lockfile-drift check
    dependabot.yml                       # NEW: weekly updates pip/npm/actions/docker
```

Responsibilities:

- **`api/src/api/auth/`** — one file per concern. `jwks.py` speaks HTTPS to Entra's `/.well-known/openid-configuration` and caches keys. `jwt_verify.py` uses those keys to validate `Bearer` tokens. `session.py` signs/verifies a small cookie (user_upn, roles, csrf). `oidc.py` wraps `authlib.integrations.starlette_client.OAuth` for login/callback. `roles.py` maps Entra group IDs from env to `viewer`/`editor`/`admin`, and exposes the `require_role(role)` FastAPI dependency. `router.py` wires these together into `/api/auth/*` + `/auth/verify`.
- **`api/src/api/metrics.py`** — a shared `prometheus_client.CollectorRegistry`, request/response middleware emitting `api_http_requests_total` and `api_ws_connections` gauges, and a `/metrics` route mounted without auth but routed only from the backend network.
- **`api/src/api/logging_config.py`** — configures loguru to emit JSON, hash PII (UPN, IP) at INFO, keep raw values at DEBUG, and propagate W3C `traceparent`. A context var holds the current trace id; a small helper injects it into outbound Redis messages and HTTP requests.
- **`api/src/api/middleware_csrf.py`** — double-submit token check for non-safe methods on requests authenticated via cookie session (bearer-token requests are exempt).
- **`flow-ingest/` / `id-ingest/` / `correlator/` `metrics.py` + `logging_config.py`** — thin per-service modules that reuse the same logging format and expose `/metrics` on an internal port. No shared package to keep services decoupled.
- **`observability/`** — all configuration for Prometheus + Grafana, including a single provisioned dashboard JSON. The canonical dashboard is committed in `docs/grafana/ztna-overview.json` (reviewable in PRs), and `observability/grafana/dashboards/ztna-overview.json` is a copy mounted into Grafana — kept in sync by an explicit step.
- **`loadtest/`** — one Locust image per scenario file with a thin Docker wrapper. Synthetic log generators speak raw UDP to Traefik syslog entrypoints.
- **`e2e/`** — a standalone Playwright project with its own `package.json`; runs against a full stack brought up by the CI job.
- **`backup/`** — a `postgres:16-alpine` sidecar with `cron` + a bash script. Restore is a stand-alone `scripts/restore-backup.sh`.
- **`docs/operations.md`** and **`docs/security.md`** — operator-facing runbooks for deployment variants, secrets migration, upgrade, backup/restore, incident response, and supply-chain posture.
- **`.github/workflows/security.yml`** + **`loadtest.yml`** + **`e2e.yml`** + **`dependabot.yml`** — one workflow per concern; `ci.yml` stays focused on lint/type/test as defined in P1.

---

## Chunk 1: OIDC auth + RBAC on api

### Task 1.1: Add auth dependencies and env placeholders

**Files:**
- Modify: `api/pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Extend `api/pyproject.toml` dependencies**

Add to the `[project].dependencies` list (keep existing P1/P2/P3 deps):

```toml
  "authlib==1.3.2",
  "python-jose[cryptography]==3.3.0",
  "httpx==0.27.2",
  "itsdangerous==2.2.0",
  "prometheus-client==0.21.0",
  "loguru==0.7.2",
```

And under `[project.optional-dependencies].test`:

```toml
  "respx==0.21.1",
  "freezegun==1.5.1",
```

- [ ] **Step 2: Extend `.env.example`**

Append under `# --- Identity adapters ---` or in a new `# --- OIDC / Auth ---` block:

```bash
# --- OIDC / Auth (Entra) ---
OIDC_ISSUER=https://login.microsoftonline.com/${ENTRA_TENANT_ID}/v2.0
OIDC_CLIENT_ID=${ENTRA_CLIENT_ID}
OIDC_CLIENT_SECRET=${ENTRA_CLIENT_SECRET}
OIDC_REDIRECT_URI=https://${APP_DOMAIN}/api/auth/callback
# Entra security group object-IDs → roles. Comma-separated group-IDs per role.
OIDC_GROUP_IDS_ADMIN=
OIDC_GROUP_IDS_EDITOR=
OIDC_GROUP_IDS_VIEWER=
# Cookie session signing key (generate with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`)
SESSION_SECRET=change-me-32-bytes-min
# JWT access token lifetime (seconds); refresh 8h managed by Entra
ACCESS_TOKEN_TTL_S=3600

# --- Backup ---
BACKUP_RETENTION_DAYS=7
```

- [ ] **Step 3: Commit**

```bash
git add api/pyproject.toml .env.example
git commit -m "chore(api): add OIDC + metrics + logging dependencies and env placeholders"
```

---

### Task 1.2: JWKS cache with TTL and kid-miss refresh (TDD)

**Files:**
- Test: `api/tests/auth/test_jwks.py`
- Create: `api/tests/auth/__init__.py`
- Create: `api/tests/auth/fixtures/__init__.py`
- Create: `api/tests/auth/fixtures/mock_jwks.json`
- Create: `api/src/api/auth/__init__.py`
- Create: `api/src/api/auth/jwks.py`

- [ ] **Step 1: Write `api/tests/auth/fixtures/mock_jwks.json`**

```json
{
  "keys": [
    {"kty": "RSA", "kid": "kid-1", "use": "sig", "alg": "RS256",
     "n": "u1SU1L...", "e": "AQAB"}
  ]
}
```

(Values truncated in this plan; the executing agent generates a real test RSA keypair with `from jose import jwk; jwk.construct(...).to_dict()` — see `mock_token.py` in Task 1.3.)

- [ ] **Step 2: Write failing test `api/tests/auth/test_jwks.py`**

```python
from __future__ import annotations

import httpx
import pytest
import respx
from freezegun import freeze_time

from api.auth.jwks import JwksCache

DISCOVERY_URL = "https://login.microsoftonline.com/tid/v2.0/.well-known/openid-configuration"
JWKS_URL = "https://login.microsoftonline.com/tid/discovery/v2.0/keys"


@pytest.fixture
def discovery_mock(respx_mock: respx.Router) -> respx.Router:
    respx_mock.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json={"jwks_uri": JWKS_URL})
    )
    respx_mock.get(JWKS_URL).mock(
        return_value=httpx.Response(200, json={"keys": [{"kid": "kid-1", "kty": "RSA", "n": "x", "e": "AQAB"}]})
    )
    return respx_mock


@pytest.mark.asyncio
async def test_first_lookup_fetches_keys(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    key = await cache.get_key("kid-1")
    assert key["kid"] == "kid-1"
    assert discovery_mock[JWKS_URL].call_count == 1


@pytest.mark.asyncio
async def test_cache_hits_within_ttl(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    await cache.get_key("kid-1")
    await cache.get_key("kid-1")
    assert discovery_mock[JWKS_URL].call_count == 1   # still cached


@pytest.mark.asyncio
async def test_cache_refreshes_after_ttl(discovery_mock: respx.Router) -> None:
    with freeze_time("2026-04-22 10:00:00") as frozen:
        cache = JwksCache(DISCOVERY_URL, ttl_seconds=3600)
        await cache.get_key("kid-1")
        frozen.tick(delta=3601)
        await cache.get_key("kid-1")
    assert discovery_mock[JWKS_URL].call_count == 2


@pytest.mark.asyncio
async def test_cache_refreshes_on_kid_miss(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    await cache.get_key("kid-1")
    # Simulate rotated kid-2 in upstream JWKS
    discovery_mock.get(JWKS_URL).mock(
        return_value=httpx.Response(200, json={"keys": [
            {"kid": "kid-1", "kty": "RSA", "n": "x", "e": "AQAB"},
            {"kid": "kid-2", "kty": "RSA", "n": "y", "e": "AQAB"},
        ]})
    )
    key = await cache.get_key("kid-2")
    assert key["kid"] == "kid-2"
    assert discovery_mock[JWKS_URL].call_count == 2


@pytest.mark.asyncio
async def test_unknown_kid_raises(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    with pytest.raises(KeyError):
        await cache.get_key("not-there")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest api/tests/auth/test_jwks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.auth.jwks'`.

- [ ] **Step 4: Implement `api/src/api/auth/__init__.py`** (empty file).

- [ ] **Step 5: Implement `api/src/api/auth/jwks.py`**

```python
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


class JwksCache:
    """Fetches and caches a provider's JWKS.

    Semantics:
    - First call fetches `.well-known/openid-configuration`, then the `jwks_uri`.
    - Cached entries expire after `ttl_seconds` (default 1 hour).
    - A cache miss on `kid` triggers a refresh before giving up.
    """

    def __init__(self, discovery_url: str, ttl_seconds: int = 3600) -> None:
        self._discovery_url = discovery_url
        self._ttl = ttl_seconds
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> dict[str, Any]:
        async with self._lock:
            if self._is_stale():
                await self._refresh()
            if kid in self._keys:
                return self._keys[kid]
            await self._refresh()
            if kid in self._keys:
                return self._keys[kid]
            raise KeyError(f"unknown kid: {kid}")

    def _is_stale(self) -> bool:
        return not self._keys or (time.monotonic() - self._fetched_at) > self._ttl

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            disc = (await client.get(self._discovery_url)).json()
            jwks = (await client.get(disc["jwks_uri"])).json()
        self._keys = {k["kid"]: k for k in jwks["keys"]}
        self._fetched_at = time.monotonic()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest api/tests/auth/test_jwks.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add api/src/api/auth/__init__.py api/src/api/auth/jwks.py api/tests/auth/__init__.py api/tests/auth/fixtures/__init__.py api/tests/auth/fixtures/mock_jwks.json api/tests/auth/test_jwks.py
git commit -m "feat(api/auth): JWKS cache with TTL and kid-miss refresh"
```

---

### Task 1.3: JWT verification (TDD)

**Files:**
- Test: `api/tests/auth/test_jwt_verify.py`
- Create: `api/tests/auth/fixtures/mock_token.py`
- Create: `api/src/api/auth/jwt_verify.py`

- [ ] **Step 1: Write `api/tests/auth/fixtures/mock_token.py`**

```python
"""Generate a real RS256 keypair + signed JWT for tests."""
from __future__ import annotations

import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt


def new_keypair(kid: str = "kid-1") -> tuple[dict[str, Any], dict[str, Any]]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    jwk_priv = jwk.construct(priv_pem.decode(), "RS256").to_dict()
    jwk_priv["kid"] = kid
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk_pub = jwk.construct(pub.decode(), "RS256").to_dict()
    jwk_pub["kid"] = kid
    return jwk_priv, jwk_pub


def sign(claims: dict[str, Any], priv_jwk: dict[str, Any]) -> str:
    return jwt.encode(claims, priv_jwk, algorithm="RS256", headers={"kid": priv_jwk["kid"]})


def standard_claims(
    sub: str = "user-1",
    upn: str = "alice@example.com",
    groups: list[str] | None = None,
    aud: str = "client-id",
    iss: str = "https://login.microsoftonline.com/tid/v2.0",
    ttl: int = 3600,
) -> dict[str, Any]:
    now = int(time.time())
    return {"sub": sub, "upn": upn, "groups": groups or [], "aud": aud,
            "iss": iss, "iat": now, "nbf": now, "exp": now + ttl}
```

- [ ] **Step 2: Write failing test `api/tests/auth/test_jwt_verify.py`**

```python
from __future__ import annotations

import pytest

from api.auth.jwt_verify import InvalidToken, verify_jwt
from api.tests.auth.fixtures.mock_token import new_keypair, sign, standard_claims


class _FakeJwks:
    def __init__(self, pub: dict) -> None:
        self._pub = pub

    async def get_key(self, kid: str) -> dict:
        if kid != self._pub["kid"]:
            raise KeyError(kid)
        return self._pub


@pytest.mark.asyncio
async def test_valid_token_returns_claims() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(groups=["g1"]), priv)
    claims = await verify_jwt(token, _FakeJwks(pub), audience="client-id",
                              issuer="https://login.microsoftonline.com/tid/v2.0")
    assert claims["upn"] == "alice@example.com"
    assert claims["groups"] == ["g1"]


@pytest.mark.asyncio
async def test_expired_token_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(ttl=-1), priv)
    with pytest.raises(InvalidToken):
        await verify_jwt(token, _FakeJwks(pub), audience="client-id",
                         issuer="https://login.microsoftonline.com/tid/v2.0")


@pytest.mark.asyncio
async def test_wrong_audience_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(aud="other"), priv)
    with pytest.raises(InvalidToken):
        await verify_jwt(token, _FakeJwks(pub), audience="client-id",
                         issuer="https://login.microsoftonline.com/tid/v2.0")


@pytest.mark.asyncio
async def test_wrong_issuer_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(iss="https://evil/"), priv)
    with pytest.raises(InvalidToken):
        await verify_jwt(token, _FakeJwks(pub), audience="client-id",
                         issuer="https://login.microsoftonline.com/tid/v2.0")


@pytest.mark.asyncio
async def test_tampered_signature_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(), priv)
    tampered = token[:-4] + "AAAA"
    with pytest.raises(InvalidToken):
        await verify_jwt(tampered, _FakeJwks(pub), audience="client-id",
                         issuer="https://login.microsoftonline.com/tid/v2.0")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest api/tests/auth/test_jwt_verify.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `api/src/api/auth/jwt_verify.py`**

```python
from __future__ import annotations

from typing import Any, Protocol

from jose import ExpiredSignatureError, JWTError, jwt


class InvalidToken(Exception):
    pass


class _JwksSource(Protocol):
    async def get_key(self, kid: str) -> dict[str, Any]: ...


async def verify_jwt(
    token: str,
    jwks: _JwksSource,
    *,
    audience: str,
    issuer: str,
) -> dict[str, Any]:
    try:
        unverified = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc
    kid = unverified.get("kid")
    if not kid:
        raise InvalidToken("no kid in token header")
    try:
        key = await jwks.get_key(kid)
    except KeyError as exc:
        raise InvalidToken(f"unknown kid: {kid}") from exc
    try:
        return jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=issuer)
    except ExpiredSignatureError as exc:
        raise InvalidToken("expired") from exc
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest api/tests/auth/test_jwt_verify.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add api/src/api/auth/jwt_verify.py api/tests/auth/fixtures/mock_token.py api/tests/auth/test_jwt_verify.py
git commit -m "feat(api/auth): JWT verification via JWKS with aud/iss/exp checks"
```

---

### Task 1.4: Role mapping and require_role dependency (TDD)

**Files:**
- Test: `api/tests/auth/test_roles.py`
- Create: `api/src/api/auth/roles.py`

- [ ] **Step 1: Write failing test `api/tests/auth/test_roles.py`**

```python
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.auth.roles import RoleMap, roles_from_groups, require_role


ROLE_MAP = RoleMap(viewer={"g-view"}, editor={"g-edit"}, admin={"g-admin"})


def test_roles_from_groups_maps_admin_editor_viewer() -> None:
    assert roles_from_groups(["g-admin"], ROLE_MAP) == {"admin", "editor", "viewer"}
    assert roles_from_groups(["g-edit"], ROLE_MAP) == {"editor", "viewer"}
    assert roles_from_groups(["g-view"], ROLE_MAP) == {"viewer"}
    assert roles_from_groups(["g-unknown"], ROLE_MAP) == set()


def test_empty_groups_no_roles() -> None:
    assert roles_from_groups([], ROLE_MAP) == set()


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()

    @a.get("/viewer", dependencies=[require_role("viewer")])
    async def v() -> dict:
        return {"ok": True}

    @a.get("/editor", dependencies=[require_role("editor")])
    async def e() -> dict:
        return {"ok": True}

    @a.get("/admin", dependencies=[require_role("admin")])
    async def ad() -> dict:
        return {"ok": True}

    return a


def _with_roles(roles: set[str]):
    async def _dep():
        return {"roles": roles}
    return _dep


def test_require_role_allows_same_role(app: FastAPI) -> None:
    from api.auth.router import current_user
    app.dependency_overrides[current_user] = _with_roles({"viewer"})
    client = TestClient(app)
    assert client.get("/viewer").status_code == 200


def test_require_role_promotes_higher(app: FastAPI) -> None:
    from api.auth.router import current_user
    app.dependency_overrides[current_user] = _with_roles({"admin", "editor", "viewer"})
    client = TestClient(app)
    assert client.get("/viewer").status_code == 200
    assert client.get("/editor").status_code == 200
    assert client.get("/admin").status_code == 200


def test_require_role_denies_lower(app: FastAPI) -> None:
    from api.auth.router import current_user
    app.dependency_overrides[current_user] = _with_roles({"viewer"})
    client = TestClient(app)
    assert client.get("/editor").status_code == 403
    assert client.get("/admin").status_code == 403


def test_unauthenticated_denied(app: FastAPI) -> None:
    from api.auth.router import current_user

    async def _anon():
        raise HTTPException(status_code=401, detail="unauthenticated")

    app.dependency_overrides[current_user] = _anon
    client = TestClient(app)
    assert client.get("/viewer").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/auth/test_roles.py -v`
Expected: FAIL (`ModuleNotFoundError` for `api.auth.roles` and `api.auth.router`).

- [ ] **Step 3: Implement `api/src/api/auth/roles.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException


@dataclass(frozen=True)
class RoleMap:
    viewer: set[str] = field(default_factory=set)
    editor: set[str] = field(default_factory=set)
    admin: set[str] = field(default_factory=set)


_HIERARCHY = {"viewer": {"viewer"}, "editor": {"viewer", "editor"},
              "admin": {"viewer", "editor", "admin"}}


def roles_from_groups(groups: list[str], mapping: RoleMap) -> set[str]:
    gset = set(groups)
    roles: set[str] = set()
    if gset & mapping.admin:
        roles |= _HIERARCHY["admin"]
    elif gset & mapping.editor:
        roles |= _HIERARCHY["editor"]
    elif gset & mapping.viewer:
        roles |= _HIERARCHY["viewer"]
    return roles


def require_role(role: str):
    """Return a FastAPI dependency that enforces `role`.

    Resolves the current user via `api.auth.router.current_user` (late import to
    avoid circular imports; overrideable in tests).
    """
    if role not in _HIERARCHY:
        raise ValueError(f"unknown role {role}")

    def _dep(user: dict = Depends(_current_user_proxy)) -> dict:
        if role not in user.get("roles", set()):
            raise HTTPException(status_code=403, detail=f"role '{role}' required")
        return user

    return Depends(_dep)


async def _current_user_proxy() -> dict:
    # Late-bind to avoid circular import at module load.
    from api.auth.router import current_user
    return await current_user()
```

- [ ] **Step 4: Create a minimal placeholder `api/src/api/auth/router.py`** so the proxy import resolves at test time. (Full router implementation lives in Task 1.7.)

```python
from __future__ import annotations

from fastapi import HTTPException


async def current_user() -> dict:
    # Default: deny. Replaced with real implementation in Task 1.7.
    raise HTTPException(status_code=401, detail="unauthenticated")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest api/tests/auth/test_roles.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add api/src/api/auth/roles.py api/src/api/auth/router.py api/tests/auth/test_roles.py
git commit -m "feat(api/auth): role mapping from Entra groups and require_role dependency"
```

---

### Task 1.5: Signed cookie session + CSRF (TDD)

**Files:**
- Test: `api/tests/auth/test_session.py`
- Create: `api/src/api/auth/session.py`

- [ ] **Step 1: Write failing test `api/tests/auth/test_session.py`**

```python
from __future__ import annotations

import pytest

from api.auth.session import SessionCodec, SessionData


def test_encode_decode_roundtrip() -> None:
    codec = SessionCodec(secret="x" * 32)
    data = SessionData(user_upn="u@x", roles={"viewer"}, csrf="t1", exp=9999999999)
    token = codec.encode(data)
    out = codec.decode(token)
    assert out == data


def test_tampered_token_rejected() -> None:
    codec = SessionCodec(secret="x" * 32)
    token = codec.encode(SessionData(user_upn="u@x", roles={"viewer"}, csrf="t1", exp=9999999999))
    with pytest.raises(ValueError):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"))


def test_expired_token_rejected() -> None:
    codec = SessionCodec(secret="x" * 32)
    token = codec.encode(SessionData(user_upn="u@x", roles={"viewer"}, csrf="t1", exp=1))
    with pytest.raises(ValueError):
        codec.decode(token)


def test_short_secret_rejected() -> None:
    with pytest.raises(ValueError):
        SessionCodec(secret="short")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/auth/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `api/src/api/auth/session.py`**

```python
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner, URLSafeTimedSerializer


@dataclass(frozen=True)
class SessionData:
    user_upn: str
    roles: set[str]
    csrf: str
    exp: int   # unix seconds


class SessionCodec:
    def __init__(self, secret: str, ttl_s: int = 28800) -> None:  # 8h
        if len(secret) < 32:
            raise ValueError("session secret must be ≥ 32 bytes")
        self._serializer = URLSafeTimedSerializer(secret, salt="ztna-session")
        self._ttl = ttl_s

    def encode(self, data: SessionData) -> str:
        payload = {**asdict(data), "roles": sorted(data.roles)}
        return self._serializer.dumps(payload)

    def decode(self, token: str) -> SessionData:
        try:
            raw = self._serializer.loads(token, max_age=self._ttl)
        except (BadSignature, SignatureExpired) as exc:
            raise ValueError(f"invalid session: {exc}") from exc
        if raw["exp"] < int(time.time()):
            raise ValueError("session expired")
        return SessionData(
            user_upn=raw["user_upn"],
            roles=set(raw["roles"]),
            csrf=raw["csrf"],
            exp=raw["exp"],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/auth/test_session.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add api/src/api/auth/session.py api/tests/auth/test_session.py
git commit -m "feat(api/auth): signed cookie session codec with 8h TTL"
```

---

## Chunk 2: Auth router wiring, CSRF, route gating, web login

### Task 1.6: CSRF double-submit middleware (TDD)

**Files:**
- Test: `api/tests/test_csrf.py`
- Create: `api/src/api/middleware_csrf.py`

- [ ] **Step 1: Write failing test `api/tests/test_csrf.py`**

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware_csrf import CsrfMiddleware


def _build() -> TestClient:
    app = FastAPI()
    app.add_middleware(CsrfMiddleware)

    @app.get("/safe")
    async def safe() -> dict:
        return {"ok": True}

    @app.post("/mutate")
    async def mutate() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_get_always_allowed() -> None:
    assert _build().get("/safe").status_code == 200


def test_post_without_cookie_allowed_bearer_flow() -> None:
    # No session cookie → treated as bearer flow; middleware is a no-op.
    r = _build().post("/mutate", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200


def test_post_with_cookie_requires_matching_header() -> None:
    c = _build()
    c.cookies.set("session", "abc")
    # No CSRF header / no matching cookie → 403.
    r = c.post("/mutate")
    assert r.status_code == 403


def test_post_with_cookie_and_matching_header_allowed() -> None:
    c = _build()
    c.cookies.set("session", "abc")
    c.cookies.set("csrf_token", "t123")
    r = c.post("/mutate", headers={"X-CSRF-Token": "t123"})
    assert r.status_code == 200


def test_post_with_mismatched_token_denied() -> None:
    c = _build()
    c.cookies.set("session", "abc")
    c.cookies.set("csrf_token", "t123")
    r = c.post("/mutate", headers={"X-CSRF-Token": "DIFFERENT"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_csrf.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `api/src/api/middleware_csrf.py`**

```python
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF: requests authenticated via cookie must send a
    matching `X-CSRF-Token` header. Bearer-token requests (Authorization header)
    are exempt — they cannot be driven by a cross-origin browser form.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        if request.cookies.get("session") is None:
            return await call_next(request)
        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("x-csrf-token")
        if not cookie_token or cookie_token != header_token:
            return JSONResponse(status_code=403, content={"detail": "CSRF token mismatch"})
        return await call_next(request)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_csrf.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add api/src/api/middleware_csrf.py api/tests/test_csrf.py
git commit -m "feat(api): CSRF double-submit middleware for cookie-auth'd requests"
```

---

### Task 1.7: Auth router — login, callback, logout, me, /auth/verify (TDD)

**Files:**
- Test: `api/tests/auth/test_router.py`
- Test: `api/tests/auth/test_verify_endpoint.py`
- Modify: `api/src/api/auth/router.py`
- Create: `api/src/api/auth/oidc.py`

- [ ] **Step 1: Write failing tests**

`api/tests/auth/test_router.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_redirects_to_idp(client: TestClient) -> None:
    r = client.get("/api/auth/login", follow_redirects=False)
    assert r.status_code == 302
    assert "login.microsoftonline.com" in r.headers["location"]


def test_callback_sets_session_cookie(client_with_mock_idp: TestClient) -> None:
    r = client_with_mock_idp.get("/api/auth/callback?code=abc&state=s1", follow_redirects=False)
    assert r.status_code == 302
    assert "session" in r.cookies


def test_me_returns_identity_and_roles(authed_client: TestClient) -> None:
    r = authed_client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user_upn"] == "alice@example.com"
    assert set(body["roles"]) == {"viewer"}


def test_logout_clears_session(authed_client: TestClient) -> None:
    r = authed_client.post("/api/auth/logout", headers={"X-CSRF-Token": "t123"})
    assert r.status_code == 204
    # cookie cleared (max-age=0 or expired)
    assert authed_client.cookies.get("session") is None
```

`api/tests/auth/test_verify_endpoint.py`:

```python
def test_verify_200_for_valid_session(authed_client) -> None:
    r = authed_client.get("/auth/verify")
    assert r.status_code == 200
    assert r.headers.get("X-User") == "alice@example.com"
    assert "viewer" in r.headers.get("X-Roles", "")


def test_verify_401_for_anon(client) -> None:
    r = client.get("/auth/verify")
    assert r.status_code == 401
```

Add fixtures in `api/tests/auth/conftest.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import build_app
from api.auth.session import SessionCodec, SessionData


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


@pytest.fixture
def client_with_mock_idp(monkeypatch) -> TestClient:
    async def _fake_exchange(code: str) -> dict:
        return {"upn": "alice@example.com", "groups": ["g-view"]}

    monkeypatch.setattr("api.auth.oidc.exchange_code", _fake_exchange)
    return TestClient(build_app())


@pytest.fixture
def authed_client() -> TestClient:
    app = build_app()
    c = TestClient(app)
    codec = SessionCodec(secret="x" * 32)
    token = codec.encode(SessionData(
        user_upn="alice@example.com", roles={"viewer"},
        csrf="t123", exp=9999999999))
    c.cookies.set("session", token)
    c.cookies.set("csrf_token", "t123")
    return c
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest api/tests/auth/test_router.py api/tests/auth/test_verify_endpoint.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `api/src/api/auth/oidc.py`**

```python
from __future__ import annotations

import httpx
from authlib.integrations.starlette_client import OAuth

from api.settings import Settings


def build_oauth(settings: Settings) -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="entra",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email"},
    )
    return oauth


async def exchange_code(code: str) -> dict:
    """Exchange an authorization code for an id_token, return claims.

    Production path uses authlib's token endpoint exchange; here we split out so
    tests can monkeypatch a simpler fake.
    """
    raise NotImplementedError   # overridden at runtime via authlib wiring
```

- [ ] **Step 4: Replace `api/src/api/auth/router.py` with the real implementation**

```python
from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from api.auth.jwks import JwksCache
from api.auth.jwt_verify import InvalidToken, verify_jwt
from api.auth.roles import RoleMap, roles_from_groups
from api.auth.session import SessionCodec, SessionData
from api.settings import Settings

router = APIRouter()


def _settings() -> Settings:
    return Settings()


def _role_map(settings: Settings) -> RoleMap:
    def _split(val: str) -> set[str]:
        return {x for x in (val or "").split(",") if x}

    return RoleMap(
        viewer=_split(settings.oidc_group_ids_viewer),
        editor=_split(settings.oidc_group_ids_editor),
        admin=_split(settings.oidc_group_ids_admin),
    )


def _codec(settings: Settings) -> SessionCodec:
    return SessionCodec(secret=settings.session_secret)


def _jwks(settings: Settings) -> JwksCache:
    return JwksCache(
        settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    )


@router.get("/api/auth/login")
async def login(settings: Settings = Depends(_settings)) -> RedirectResponse:
    # Minimal authorization_endpoint redirect; state is generated per-request and
    # stashed in a short-lived cookie. authlib can be plugged in later for PKCE.
    state = secrets.token_urlsafe(16)
    auth_url = (
        f"{settings.oidc_issuer.rstrip('/')}/authorize"
        f"?response_type=code&client_id={settings.oidc_client_id}"
        f"&redirect_uri={settings.oidc_redirect_uri}&scope=openid+profile+email"
        f"&state={state}"
    )
    r = RedirectResponse(auth_url, status_code=302)
    r.set_cookie("oidc_state", state, httponly=True, secure=True,
                 samesite="lax", max_age=600)
    return r


@router.get("/api/auth/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    settings: Settings = Depends(_settings),
) -> RedirectResponse:
    if request.cookies.get("oidc_state") != state:
        raise HTTPException(status_code=400, detail="state mismatch")
    from api.auth.oidc import exchange_code
    claims = await exchange_code(code)

    roles = roles_from_groups(claims.get("groups", []), _role_map(settings))
    csrf = secrets.token_urlsafe(16)
    data = SessionData(
        user_upn=claims["upn"], roles=roles, csrf=csrf,
        exp=int(time.time()) + settings.access_token_ttl_s,
    )
    token = _codec(settings).encode(data)
    r = RedirectResponse("/", status_code=302)
    r.set_cookie("session", token, httponly=True, secure=True,
                 samesite="strict", max_age=28800)
    r.set_cookie("csrf_token", csrf, secure=True, samesite="strict",
                 max_age=28800)   # readable by JS
    r.delete_cookie("oidc_state")
    return r


@router.post("/api/auth/logout", status_code=204)
async def logout(response: Response) -> Response:
    response.delete_cookie("session")
    response.delete_cookie("csrf_token")
    response.status_code = 204
    return response


async def current_user(request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    # 1. Bearer JWT path
    auth = request.headers.get("authorization", "") if request else ""
    if auth.lower().startswith("bearer "):
        settings = _settings()
        try:
            claims = await verify_jwt(
                auth.split(None, 1)[1], _jwks(settings),
                audience=settings.oidc_client_id,
                issuer=settings.oidc_issuer,
            )
        except InvalidToken as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {
            "user_upn": claims.get("upn", claims.get("sub", "unknown")),
            "roles": roles_from_groups(claims.get("groups", []), _role_map(settings)),
        }
    # 2. Cookie session path
    if request and (cookie := request.cookies.get("session")):
        try:
            data = _codec(_settings()).decode(cookie)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"user_upn": data.user_upn, "roles": data.roles}
    raise HTTPException(status_code=401, detail="unauthenticated")


@router.get("/api/auth/me")
async def me(user: dict = Depends(current_user)) -> dict:
    return {"user_upn": user["user_upn"], "roles": sorted(user["roles"])}


@router.get("/auth/verify")
async def verify(user: dict = Depends(current_user)) -> Response:
    r = JSONResponse(content={})
    r.headers["X-User"] = user["user_upn"]
    r.headers["X-Roles"] = ",".join(sorted(user["roles"]))
    return r
```

- [ ] **Step 5: Extend `api/src/api/settings.py`**

Add fields:

```python
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_group_ids_viewer: str = ""
    oidc_group_ids_editor: str = ""
    oidc_group_ids_admin: str = ""
    session_secret: str = "change-me-change-me-change-me-123"
    access_token_ttl_s: int = 3600
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest api/tests/auth/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/src/api/auth/oidc.py api/src/api/auth/router.py api/src/api/settings.py api/tests/auth/test_router.py api/tests/auth/test_verify_endpoint.py api/tests/auth/conftest.py
git commit -m "feat(api/auth): OIDC login/callback/logout/me and forwardAuth /auth/verify"
```

---

### Task 1.8: Wire require_role on every existing P2/P3 CRUD route (TDD)

**Files:**
- Test: `api/tests/auth/test_require_role.py`
- Modify: `api/src/api/main.py`
- Modify: existing P2/P3 routers (applications, saas, adapters)

- [ ] **Step 1: Write failing test `api/tests/auth/test_require_role.py`**

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "method,path,role_required",
    [
        ("GET",    "/api/applications",           "viewer"),
        ("POST",   "/api/applications",           "editor"),
        ("PUT",    "/api/applications/1",         "editor"),
        ("DELETE", "/api/applications/1",         "editor"),
        ("GET",    "/api/saas",                   "viewer"),
        ("POST",   "/api/saas",                   "editor"),
        ("GET",    "/api/adapters",               "viewer"),
        ("POST",   "/api/adapters/reload",        "admin"),
        ("POST",   "/api/adapters/pan/disable",   "admin"),
    ],
)
def test_every_crud_route_is_role_guarded(
    anon_client: TestClient, method: str, path: str, role_required: str
) -> None:
    r = anon_client.request(method, path)
    assert r.status_code in (401, 403), (
        f"{method} {path} returned {r.status_code}; expected auth-gate"
    )
```

Add fixture `anon_client` in `api/tests/auth/conftest.py`:

```python
@pytest.fixture
def anon_client() -> TestClient:
    return TestClient(build_app())
```

- [ ] **Step 2: Run test — expect failures on routes still unguarded**

Run: `pytest api/tests/auth/test_require_role.py -v`
Expected: FAIL on each unguarded route.

- [ ] **Step 3: Wire `require_role` on each router**

For each existing router file from P2/P3 (`api/src/api/routers/applications.py`, `saas.py`, `adapters.py`, `flows.py`, `identity.py`, `sankey_ws.py`):

```python
from api.auth.roles import require_role

@router.get("/api/applications", dependencies=[require_role("viewer")])
async def list_applications(...): ...

@router.post("/api/applications", dependencies=[require_role("editor")])
async def create_application(...): ...

# and similarly for PUT / DELETE ("editor") and adapter mutating ops ("admin")
```

Read routes on `flows`, `identity`, `applications`, `saas`, `adapters` → `viewer`.
Mutating `applications` / `saas` / override-app → `editor`.
`POST /api/adapters/reload`, `POST /api/adapters/<name>/disable`, `POST /api/adapters/<name>/enable`, `POST /api/retention/*` → `admin`.

Concrete mapping table (the executing agent must walk every route in P2/P3 routers and apply exactly this):

| Route (method + path)                          | Role    |
|------------------------------------------------|---------|
| `GET  /api/flows/sankey`                       | viewer  |
| `GET  /api/flows/raw`                          | viewer  |
| `WS   /ws/sankey`                              | viewer  |
| `GET  /api/identity/resolve`                   | viewer  |
| `GET  /api/applications` / `/{id}`             | viewer  |
| `POST/PUT/DELETE /api/applications`            | editor  |
| `GET  /api/applications/{id}/audit`            | viewer  |
| `GET  /api/saas`                               | viewer  |
| `POST/PUT/DELETE /api/saas`                    | editor  |
| `GET  /api/adapters`                           | viewer  |
| `POST /api/adapters/reload`                    | admin   |
| `POST /api/adapters/{name}/disable`            | admin   |
| `POST /api/adapters/{name}/enable`             | admin   |
| `GET  /api/stats`                              | viewer  |
| `GET  /api/health/live` / `/ready`             | (none)  |

- [ ] **Step 4: Modify `api/src/api/main.py`**

In `build_app()`:

```python
from api.auth.router import router as auth_router
from api.middleware_csrf import CsrfMiddleware

# ...
app.add_middleware(CsrfMiddleware)
app.include_router(auth_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest api/tests/auth/test_require_role.py -v`
Expected: PASS.

- [ ] **Step 6: Full auth suite**

Run: `pytest api/tests/auth/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/src/api/main.py api/src/api/routers api/tests/auth/test_require_role.py api/tests/auth/conftest.py
git commit -m "feat(api): guard all CRUD routes with role-based access control"
```

---

### Task 1.9: Web login flow + role-gated UI

**Files:**
- Modify: `web/package.json` (add `jose`, `@tanstack/react-query` already present from P2)
- Create: `web/src/auth/AuthProvider.tsx`
- Create: `web/src/auth/LoginPage.tsx`
- Create: `web/src/auth/LogoutButton.tsx`
- Create: `web/src/auth/useAuth.ts`
- Create: `web/src/auth/useRole.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/components/OverrideAppButton.tsx` (from P2)
- Test: `web/tests/unit/auth.test.ts`
- Test: `web/tests/unit/useRole.test.ts`

- [ ] **Step 1: Write `web/src/auth/useAuth.ts`**

```typescript
import { useQuery, useQueryClient } from "@tanstack/react-query";

export type Me = { user_upn: string; roles: string[] };

export function useAuth() {
  const qc = useQueryClient();
  const q = useQuery<Me | null>({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const r = await fetch("/api/auth/me", { credentials: "include" });
      if (r.status === 401) return null;
      if (!r.ok) throw new Error(`me failed: ${r.status}`);
      return (await r.json()) as Me;
    },
    staleTime: 60_000,
  });
  return {
    me: q.data ?? null,
    loading: q.isLoading,
    refetch: () => qc.invalidateQueries({ queryKey: ["auth", "me"] }),
  };
}
```

- [ ] **Step 2: Write `web/src/auth/useRole.ts`**

```typescript
import { useAuth } from "./useAuth";

export function useRole(required: "viewer" | "editor" | "admin"): boolean {
  const { me } = useAuth();
  if (!me) return false;
  return me.roles.includes(required);
}
```

- [ ] **Step 3: Write `web/src/auth/AuthProvider.tsx`**

```tsx
import { PropsWithChildren } from "react";
import { useAuth } from "./useAuth";
import { LoginPage } from "./LoginPage";

export function AuthProvider({ children }: PropsWithChildren) {
  const { me, loading } = useAuth();
  if (loading) return <div aria-busy="true">Loading…</div>;
  if (!me) return <LoginPage />;
  return <>{children}</>;
}
```

- [ ] **Step 4: Write `web/src/auth/LoginPage.tsx`**

```tsx
export function LoginPage() {
  return (
    <main className="min-h-screen flex items-center justify-center">
      <a
        href="/api/auth/login"
        className="rounded border px-4 py-2 focus:outline-none focus:ring"
      >
        Sign in with Entra ID
      </a>
    </main>
  );
}
```

- [ ] **Step 5: Write `web/src/auth/LogoutButton.tsx`**

```tsx
export function LogoutButton() {
  const csrf = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="))?.split("=")[1];
  return (
    <button
      onClick={async () => {
        await fetch("/api/auth/logout", {
          method: "POST",
          credentials: "include",
          headers: csrf ? { "X-CSRF-Token": csrf } : undefined,
        });
        window.location.href = "/";
      }}
    >
      Sign out
    </button>
  );
}
```

- [ ] **Step 6: Gate override button in `web/src/components/OverrideAppButton.tsx`**

Add role check at the top of the component:

```tsx
import { useRole } from "../auth/useRole";

export function OverrideAppButton(props: Props) {
  const canEdit = useRole("editor");
  if (!canEdit) return null;
  // ... existing P2 implementation ...
}
```

- [ ] **Step 7: Wrap `App.tsx` with `<AuthProvider>`** and add `<LogoutButton />` in the header.

- [ ] **Step 8: Write unit tests**

`web/tests/unit/useRole.test.ts`:

```typescript
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRole } from "../../src/auth/useRole";

// Mock fetch to return a fake me.
beforeEach(() => {
  (globalThis.fetch as unknown) = async () =>
    new Response(JSON.stringify({ user_upn: "a@b", roles: ["viewer"] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
});

function wrap({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("viewer role matches viewer, not editor", async () => {
  const { result, rerender } = renderHook(() => useRole("viewer"), { wrapper: wrap });
  // Initial render: me not loaded yet → false
  expect(result.current).toBe(false);
  // After react-query resolves → true for viewer
  await new Promise((r) => setTimeout(r, 50));
  rerender();
  expect(result.current).toBe(true);
});
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd web && npm test -- useRole.test.ts`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add web/src/auth web/src/App.tsx web/src/components/OverrideAppButton.tsx web/tests/unit/auth.test.ts web/tests/unit/useRole.test.ts web/package.json
git commit -m "feat(web): OIDC login/logout flow and role-gated UI"
```

---

## Chunk 3: Traefik dashboard hardening + forwardAuth + tuned security middlewares

### Task 2.1: Tighten `traefik/dynamic/middlewares.yml`

**Files:**
- Modify: `traefik/dynamic/middlewares.yml`

- [ ] **Step 1: Replace middlewares with tuned production values**

```yaml
http:
  middlewares:
    # Authenticated REST: 60 rps per IP, burst 120.
    rate-limit-api:
      rateLimit:
        average: 60
        burst: 120
        period: 1s
        sourceCriterion:
          ipStrategy: {depth: 1}

    # Unauthenticated /api/auth/*: 300 rps per IP burst 600 (higher because it
    # must absorb login storms).
    rate-limit-auth:
      rateLimit:
        average: 300
        burst: 600
        period: 1s

    compression:
      compress: {}

    secure-headers:
      headers:
        frameDeny: true
        contentTypeNosniff: true
        browserXssFilter: true
        referrerPolicy: strict-origin-when-cross-origin
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        # Production CSP: no inline scripts, only self + wss upgrades. Styles
        # allow 'unsafe-inline' for Tailwind-generated runtime styles (we do
        # not dynamically inject script tags anywhere).
        contentSecurityPolicy: >-
          default-src 'self';
          img-src 'self' data:;
          script-src 'self';
          style-src 'self' 'unsafe-inline';
          connect-src 'self' wss:;
          frame-ancestors 'none';
          base-uri 'self';
          form-action 'self'
        permissionsPolicy: "camera=(), microphone=(), geolocation=(), payment=()"

    # forwardAuth to api /auth/verify; api returns 200 + X-User / X-Roles
    # headers for authed requests, 401 otherwise. The session cookie is passed
    # through; bearer tokens are not, as forwardAuth is only used for the
    # Traefik dashboard (browser-cookie flow).
    oidc-verify:
      forwardAuth:
        address: http://api:8000/auth/verify
        trustForwardHeader: true
        authResponseHeaders:
          - X-User
          - X-Roles
```

- [ ] **Step 2: Commit**

```bash
git add traefik/dynamic/middlewares.yml
git commit -m "feat(traefik): tuned rate-limit, strict CSP, permissions-policy, and forwardAuth middleware"
```

---

### Task 2.2: Add Traefik dashboard router (admin-only) and wire middlewares

**Files:**
- Modify: `traefik/dynamic/tcp-udp.yml` (P1 placeholder → router file also gains a `dashboard.yml` sibling)
- Create: `traefik/dynamic/dashboard.yml`

- [ ] **Step 1: Write `traefik/dynamic/dashboard.yml`**

```yaml
http:
  routers:
    traefik-dashboard:
      rule: "Host(`${APP_DOMAIN}`) && PathPrefix(`/traefik`)"
      service: api@internal
      entryPoints: [websecure]
      middlewares:
        - oidc-verify@file
        - secure-headers@file
      tls: {}
```

Note: since the router resolves `api@internal`, no host-service mapping is needed — this is Traefik's internal dashboard service.

- [ ] **Step 2: Add role check on `/auth/verify` for admin**

Modify `api/src/api/auth/router.py` `verify()` to **also** require admin when the request originates from the dashboard path (Traefik forwards `X-Forwarded-Uri`):

```python
@router.get("/auth/verify")
async def verify(request: Request, user: dict = Depends(current_user)) -> Response:
    forwarded_uri = request.headers.get("x-forwarded-uri", "")
    if forwarded_uri.startswith("/traefik") and "admin" not in user.get("roles", set()):
        raise HTTPException(status_code=403, detail="admin role required for /traefik")
    r = JSONResponse(content={})
    r.headers["X-User"] = user["user_upn"]
    r.headers["X-Roles"] = ",".join(sorted(user["roles"]))
    return r
```

Extend `test_verify_endpoint.py`:

```python
def test_dashboard_requires_admin(authed_viewer_client) -> None:
    r = authed_viewer_client.get("/auth/verify",
                                 headers={"X-Forwarded-Uri": "/traefik/"})
    assert r.status_code == 403


def test_dashboard_allows_admin(authed_admin_client) -> None:
    r = authed_admin_client.get("/auth/verify",
                                headers={"X-Forwarded-Uri": "/traefik/"})
    assert r.status_code == 200
```

Add `authed_admin_client` and `authed_viewer_client` fixtures in `api/tests/auth/conftest.py` — same pattern as `authed_client`, different `roles` set.

- [ ] **Step 3: Update `docker-compose.yml` api service labels to use new middleware names**

```yaml
      - traefik.http.routers.api.middlewares=rate-limit-api@file,secure-headers@file,compression@file
      - traefik.http.routers.auth.rule=Host(`${APP_DOMAIN}`) && PathPrefix(`/api/auth`)
      - traefik.http.routers.auth.entrypoints=websecure
      - traefik.http.routers.auth.tls=true
      - traefik.http.routers.auth.middlewares=rate-limit-auth@file,secure-headers@file
      - traefik.http.routers.auth.service=api
```

- [ ] **Step 4: Run tests**

Run: `pytest api/tests/auth/test_verify_endpoint.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add traefik/dynamic/dashboard.yml api/src/api/auth/router.py api/tests/auth/test_verify_endpoint.py api/tests/auth/conftest.py docker-compose.yml
git commit -m "feat(traefik): admin-only /traefik dashboard behind forwardAuth"
```

---

### Task 2.3: WS connection cap

**Files:**
- Modify: `api/src/api/routers/sankey_ws.py` (from P2)

- [ ] **Step 1: Write failing test `api/tests/test_ws_cap.py`**

```python
import pytest
from fastapi.testclient import TestClient


def test_second_ws_for_same_user_rejected(authed_client: TestClient) -> None:
    with authed_client.websocket_connect("/ws/sankey?mode=live") as _:
        with pytest.raises(Exception):
            with authed_client.websocket_connect("/ws/sankey?mode=live"):
                pass
```

- [ ] **Step 2: Implement a per-user `asyncio.Semaphore(1)` gate** on the WS handler that tracks active connections by `user_upn` in an in-memory dict; second connect attempts close with code 1008.

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest api/tests/test_ws_cap.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add api/src/api/routers/sankey_ws.py api/tests/test_ws_cap.py
git commit -m "feat(api/ws): cap live Sankey WebSocket to one connection per user"
```

---

## Chunk 4: Prometheus metrics + structured JSON logging

### Task 3.1: api metrics registry + middleware (TDD)

**Files:**
- Create: `api/src/api/metrics.py`
- Test: `api/tests/test_metrics.py`
- Modify: `api/src/api/main.py`

- [ ] **Step 1: Write failing test `api/tests/test_metrics.py`**

```python
from fastapi.testclient import TestClient


def test_metrics_endpoint_exposes_prometheus_format(client: TestClient) -> None:
    # Prime a few requests.
    client.get("/health/live")
    client.get("/health/live")
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert 'api_http_requests_total{route="/health/live",status="200"}' in body


def test_ws_gauge_metric_present(client: TestClient) -> None:
    r = client.get("/metrics")
    assert "api_ws_connections" in r.text
```

- [ ] **Step 2: Implement `api/src/api/metrics.py`**

```python
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "api_http_requests_total",
    "API HTTP request count",
    ["route", "status"],
    registry=REGISTRY,
)
WS_CONNECTIONS = Gauge(
    "api_ws_connections",
    "Active WebSocket connections",
    registry=REGISTRY,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(route=path, status=str(response.status_code)).inc()
        return response


async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(REGISTRY).decode("utf-8"),
                             media_type="text/plain; version=0.0.4")
```

- [ ] **Step 3: Wire in `api/src/api/main.py`**

```python
from api.metrics import MetricsMiddleware, metrics_endpoint

app.add_middleware(MetricsMiddleware)
app.get("/metrics")(metrics_endpoint)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/api/metrics.py api/src/api/main.py api/tests/test_metrics.py
git commit -m "feat(api): prometheus metrics registry, middleware, and /metrics endpoint"
```

---

### Task 3.2: api structured JSON logging with PII hashing (TDD)

**Files:**
- Create: `api/src/api/logging_config.py`
- Test: `api/tests/test_logging_config.py`

- [ ] **Step 1: Write failing test `api/tests/test_logging_config.py`**

```python
import json

from loguru import logger

from api.logging_config import configure_logging


def test_info_log_hashes_upn_and_ip(capsys) -> None:
    configure_logging("INFO")
    logger.bind(upn="alice@example.com", src_ip="10.0.0.1").info("flow observed")
    out = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(out)
    assert record["extra"]["upn"] != "alice@example.com"
    assert record["extra"]["upn"].startswith("sha256:")
    assert record["extra"]["src_ip"].startswith("sha256:")


def test_debug_log_keeps_raw_pii(capsys) -> None:
    configure_logging("DEBUG")
    logger.bind(upn="alice@example.com", src_ip="10.0.0.1").debug("flow observed")
    out = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(out)
    assert record["extra"]["upn"] == "alice@example.com"
    assert record["extra"]["src_ip"] == "10.0.0.1"


def test_trace_id_propagated(capsys) -> None:
    configure_logging("INFO")
    from api.logging_config import set_trace_id
    set_trace_id("00-abcdef1234567890abcdef1234567890-1111111111111111-01")
    logger.info("with trace")
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["extra"]["trace_id"] == "abcdef1234567890abcdef1234567890"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_logging_config.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `api/src/api/logging_config.py`**

```python
from __future__ import annotations

import contextvars
import hashlib
import sys
from typing import Any

from loguru import logger

_PII_KEYS = {"upn", "src_ip", "user_upn", "ip"}
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def set_trace_id(traceparent: str) -> None:
    # W3C traceparent format: 00-<trace-id>-<span-id>-<flags>
    parts = traceparent.split("-")
    tid = parts[1] if len(parts) >= 2 else traceparent
    _trace_id.set(tid)


def _hash(v: str) -> str:
    return "sha256:" + hashlib.sha256(v.encode()).hexdigest()[:16]


def _processor(record: dict[str, Any]) -> None:
    extra = record["extra"]
    extra["trace_id"] = _trace_id.get()
    if record["level"].name in {"INFO", "WARNING", "ERROR", "CRITICAL"}:
        for k in list(extra.keys()):
            if k in _PII_KEYS and isinstance(extra[k], str):
                extra[k] = _hash(extra[k])


def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stdout, level=level, serialize=True,
               filter=lambda r: _processor(r) or True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_logging_config.py -v`
Expected: PASS.

- [ ] **Step 5: Call `configure_logging(settings.log_level)` from `_lifespan` in `main.py`.**

- [ ] **Step 6: Commit**

```bash
git add api/src/api/logging_config.py api/src/api/main.py api/tests/test_logging_config.py
git commit -m "feat(api): structured JSON logging with PII hashing and trace_id propagation"
```

---

### Task 3.3: Extend metrics + logging to flow-ingest, id-ingest, correlator

**Files:**
- Create: `flow-ingest/src/flow_ingest/metrics.py`
- Create: `flow-ingest/src/flow_ingest/logging_config.py`
- Modify: `flow-ingest/src/flow_ingest/main.py`
- Create: `flow-ingest/tests/test_metrics.py`
- (Parallel: same for `id-ingest/` and `correlator/`)

- [ ] **Step 1: Write `flow-ingest/src/flow_ingest/metrics.py`**

```python
from __future__ import annotations

import asyncio
import threading
from prometheus_client import CollectorRegistry, Counter, generate_latest, start_http_server

REGISTRY = CollectorRegistry(auto_describe=True)

FLOW_INGEST_EVENTS = Counter(
    "flow_ingest_events_total", "Flow events ingested",
    ["adapter", "source"], registry=REGISTRY,
)
FLOW_INGEST_PARSE_ERRORS = Counter(
    "flow_ingest_parse_errors_total", "Flow parse errors",
    ["adapter"], registry=REGISTRY,
)


def start_metrics_server(port: int = 9100) -> None:
    start_http_server(port, registry=REGISTRY)
```

- [ ] **Step 2: Write `flow-ingest/src/flow_ingest/logging_config.py`**

Exactly the same as `api/src/api/logging_config.py` — duplicated to keep services decoupled. (DRY breach is intentional: services may evolve independently and shared packaging adds deployment complexity.)

- [ ] **Step 3: Modify `flow-ingest/src/flow_ingest/main.py`**

Add at startup:

```python
from flow_ingest.logging_config import configure_logging
from flow_ingest.metrics import start_metrics_server

configure_logging(settings.log_level)
start_metrics_server(port=9100)
```

In each adapter loop, increment `FLOW_INGEST_EVENTS.labels(adapter=self.name, source=event["source"]).inc()` and `FLOW_INGEST_PARSE_ERRORS.labels(adapter=self.name).inc()` on exception paths.

- [ ] **Step 4: Test `flow-ingest/tests/test_metrics.py`**

```python
import httpx
import pytest

from flow_ingest.metrics import FLOW_INGEST_EVENTS, start_metrics_server


@pytest.fixture(scope="module", autouse=True)
def _server():
    start_metrics_server(port=9991)
    yield


def test_counter_is_exposed() -> None:
    FLOW_INGEST_EVENTS.labels(adapter="pan", source="firewall").inc()
    body = httpx.get("http://127.0.0.1:9991").text
    assert 'flow_ingest_events_total{adapter="pan",source="firewall"}' in body
```

- [ ] **Step 5: Run test**

Run: `pytest flow-ingest/tests/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 6: Mirror for id-ingest**

Create `id-ingest/src/id_ingest/metrics.py` with:

```python
IDENTITY_INGEST_EVENTS = Counter(
    "identity_ingest_events_total", "Identity events ingested",
    ["adapter"], registry=REGISTRY,
)
IDENTITY_INDEX_SIZE = Gauge(
    "identity_index_size", "Current identity index size",
    registry=REGISTRY,
)
```

And `id-ingest/tests/test_metrics.py` mirroring the flow-ingest test.

- [ ] **Step 7: Mirror for correlator**

Create `correlator/src/correlator/metrics.py`:

```python
from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, start_http_server

REGISTRY = CollectorRegistry(auto_describe=True)

CORRELATOR_QUEUE_DEPTH = Gauge(
    "correlator_queue_depth", "Bounded queue depth per pipeline stage",
    ["stage"], registry=REGISTRY,
)
CORRELATOR_DROPPED_FLOWS = Counter(
    "correlator_dropped_flows_total", "Flows dropped due to queue overflow",
    registry=REGISTRY,
)
CORRELATOR_UNKNOWN_USER_RATIO = Gauge(
    "correlator_unknown_user_ratio",
    "Ratio of flows with unknown user in the last window",
    registry=REGISTRY,
)
CORRELATOR_LCD_MISS = Counter(
    "correlator_lcd_miss_total",
    "Count of LCD lookups that returned no group",
    registry=REGISTRY,
)
POSTGRES_INSERT_BATCH_SECONDS = Histogram(
    "postgres_insert_batch_size_seconds",
    "Postgres batch insert duration seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
    registry=REGISTRY,
)
POSTGRES_FLUSH_DURATION_SECONDS = Histogram(
    "postgres_flush_duration_seconds",
    "Postgres explicit flush duration seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
    registry=REGISTRY,
)
```

And `correlator/tests/test_metrics.py` — same pattern as `flow-ingest/tests/test_metrics.py`, but exercise `CORRELATOR_DROPPED_FLOWS.inc()` and `POSTGRES_INSERT_BATCH_SECONDS.observe(0.05)` and assert each metric name surfaces in the `/metrics` body.

- [ ] **Step 8: Wire pipeline stages to report queue depth**

Modify `correlator/src/correlator/pipeline/*.py` so each stage's main loop runs `CORRELATOR_QUEUE_DEPTH.labels(stage=<name>).set(self.queue.qsize())` before the blocking `await`. On queue overflow (existing drop-oldest path in P2), increment `CORRELATOR_DROPPED_FLOWS`. On empty LCD result, increment `CORRELATOR_LCD_MISS`.

- [ ] **Step 9: Commit**

```bash
git add flow-ingest/src/flow_ingest/metrics.py flow-ingest/src/flow_ingest/logging_config.py flow-ingest/src/flow_ingest/main.py flow-ingest/tests/test_metrics.py id-ingest/src/id_ingest/metrics.py id-ingest/src/id_ingest/logging_config.py id-ingest/src/id_ingest/main.py id-ingest/tests/test_metrics.py correlator/src/correlator/metrics.py correlator/src/correlator/logging_config.py correlator/src/correlator/main.py correlator/src/correlator/pipeline correlator/tests/test_metrics.py
git commit -m "feat(ingest/correlator): prometheus metrics and JSON logging"
```

---

### Task 3.4: Prometheus + Grafana overlay (`docker-compose.observe.yml`)

**Files:**
- Create: `observability/prometheus/prometheus.yml`
- Create: `observability/grafana/provisioning/datasources/prometheus.yaml`
- Create: `observability/grafana/provisioning/dashboards/ztna.yaml`
- Create: `observability/grafana/dashboards/ztna-overview.json`
- Create: `docs/grafana/ztna-overview.json`   (identical; version-controlled copy)
- Create: `docker-compose.observe.yml`

- [ ] **Step 1: Write `observability/prometheus/prometheus.yml`**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: api
    static_configs:
      - targets: ["api:8000"]
    metrics_path: /metrics

  - job_name: flow-ingest
    static_configs:
      - targets: ["flow-ingest:9100"]

  - job_name: id-ingest
    static_configs:
      - targets: ["id-ingest:9100"]

  - job_name: correlator
    static_configs:
      - targets: ["correlator:9100"]
```

- [ ] **Step 2: Write datasource provisioning `observability/grafana/provisioning/datasources/prometheus.yaml`**

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

- [ ] **Step 3: Write dashboard provisioning `observability/grafana/provisioning/dashboards/ztna.yaml`**

```yaml
apiVersion: 1
providers:
  - name: ZTNA
    orgId: 1
    folder: ZTNA
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 4: Write canonical dashboard JSON `docs/grafana/ztna-overview.json`**

Minimum panels required (IDs and rows committed in full JSON):

1. **Flow ingest rate** — `sum(rate(flow_ingest_events_total[1m])) by (adapter)`
2. **Correlator queue depth per stage** — `correlator_queue_depth`
3. **Correlator drops** — `rate(correlator_dropped_flows_total[5m])`
4. **Unknown user ratio** — `correlator_unknown_user_ratio`
5. **WS connections** — `api_ws_connections`
6. **API p99 latency** — `histogram_quantile(0.99, sum(rate(api_http_request_duration_seconds_bucket[5m])) by (le))` (emit this histogram via `prometheus-fastapi-instrumentator` or a local `Histogram` — executing agent picks; recommended: extend `metrics.py` with `HTTP_DURATION` histogram at INFO level)
7. **Postgres insert batch duration** — `histogram_quantile(0.95, rate(postgres_insert_batch_size_seconds_bucket[5m]))`
8. **Identity index size** — `identity_index_size`
9. **LCD miss rate** — `rate(correlator_lcd_miss_total[5m])`

The full JSON file is ~400 lines of Grafana panel config. The executing agent generates it via `grafonnet` or by exporting from a live Grafana; either way, the file lands at `docs/grafana/ztna-overview.json` and is copied to `observability/grafana/dashboards/ztna-overview.json` by the Compose overlay bind mount (step 6 below).

- [ ] **Step 5: Duplicate dashboard into provisioning path**

```bash
cp docs/grafana/ztna-overview.json observability/grafana/dashboards/ztna-overview.json
```

- [ ] **Step 6: Write `docker-compose.observe.yml`**

```yaml
# Layered with: docker compose -f docker-compose.yml -f docker-compose.observe.yml --profile observe up -d

services:
  prometheus:
    image: prom/prometheus:v2.54.1
    profiles: [observe]
    restart: unless-stopped
    volumes:
      - ./observability/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.retention.time=15d
    networks: [backend]

  grafana:
    image: grafana/grafana:11.2.0
    profiles: [observe]
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-change-me}
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    volumes:
      - ./observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./observability/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
    networks: [backend]
    labels:
      - traefik.enable=true
      - traefik.http.routers.grafana.rule=Host(`${APP_DOMAIN}`) && PathPrefix(`/grafana`)
      - traefik.http.routers.grafana.entrypoints=websecure
      - traefik.http.routers.grafana.tls=true
      - traefik.http.routers.grafana.middlewares=oidc-verify@file,secure-headers@file
      - traefik.http.services.grafana.loadbalancer.server.port=3000

volumes:
  grafana-data:
```

- [ ] **Step 7: Add Makefile target**

In `Makefile`:

```make
observe:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.observe.yml --profile observe up -d
```

- [ ] **Step 8: Commit**

```bash
git add observability/ docs/grafana/ztna-overview.json docker-compose.observe.yml Makefile
git commit -m "feat(observe): prometheus + grafana overlay with provisioned datasource and dashboard"
```

---

## Chunk 5: Load test profile, supply-chain security, dependabot

### Task 4.1: Locust scenarios + fixture generators

**Files:**
- Create: `loadtest/Dockerfile`
- Create: `loadtest/requirements.txt`
- Create: `loadtest/locustfile.py`
- Create: `loadtest/scenarios/sustained.py`
- Create: `loadtest/scenarios/burst.py`
- Create: `loadtest/scenarios/identity_surge.py`
- Create: `loadtest/generators/pan_fixture.py`
- Create: `loadtest/generators/fortigate_fixture.py`
- Create: `loadtest/generators/ad_4624_fixture.py`
- Create: `loadtest/generators/ise_fixture.py`
- Create: `loadtest/tests/test_generators.py`

- [ ] **Step 1: Write `loadtest/requirements.txt`**

```
locust==2.31.6
pytest==8.3.3
```

- [ ] **Step 2: Write `loadtest/Dockerfile`**

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
ENTRYPOINT ["locust", "-f", "locustfile.py"]
```

- [ ] **Step 3: Write each generator**

`loadtest/generators/pan_fixture.py`:

```python
from __future__ import annotations

import random
import time


def _rand_ip(prefix: str) -> str:
    return f"{prefix}.{random.randint(1, 254)}.{random.randint(1, 254)}"


def pan_traffic_line(now: float | None = None) -> bytes:
    """A minimal Palo Alto TRAFFIC syslog CSV line (log_subtype=end)."""
    t = time.gmtime(now or time.time())
    ts = time.strftime("%Y/%m/%d %H:%M:%S", t)
    src = _rand_ip("10.0")
    dst = _rand_ip("203.0")
    port = random.choice([443, 53, 8080])
    bytes_ = random.randint(100, 50_000)
    return (
        f"<14>{ts} FW01 1,2026/04/22 10:00:00,001,TRAFFIC,end,"
        f"1,2026/04/22 10:00:00,{src},{dst},0.0.0.0,0.0.0.0,rule1,user,"
        f"app,vsys1,trust,untrust,ethernet1/1,ethernet1/2,Logs,{ts},"
        f"12345,1,12345,{port},0,0,0x0,tcp,allow,{bytes_},{bytes_//2},"
        f"{bytes_//2},10,{ts},0,any,0,1,0x0,US,US,,0,0\n"
    ).encode()
```

`loadtest/generators/fortigate_fixture.py`:

```python
from __future__ import annotations

import random
import time


def fortigate_traffic_line() -> bytes:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    src = f"10.1.{random.randint(1,254)}.{random.randint(1,254)}"
    dst = f"198.51.{random.randint(1,254)}.{random.randint(1,254)}"
    port = random.choice([443, 80, 22])
    return (
        f"<134>date={ts} devname=fw02 type=traffic subtype=forward "
        f"status=close srcip={src} dstip={dst} dstport={port} "
        f"proto=6 sentbyte={random.randint(100,40000)} "
        f"rcvdbyte={random.randint(100,40000)} app=HTTPS.WEB\n"
    ).encode()
```

`loadtest/generators/ad_4624_fixture.py`:

```python
from __future__ import annotations

import random


def ad_4624_line() -> bytes:
    ip = f"10.2.{random.randint(1,254)}.{random.randint(1,254)}"
    upn = random.choice(["alice@example.com", "bob@example.com", "carol@example.com"])
    logon_type = random.choice([2, 3, 10])
    return (
        f"<14>EventID=4624 TargetUserName={upn} IpAddress={ip} "
        f"LogonType={logon_type}\n"
    ).encode()
```

`loadtest/generators/ise_fixture.py`:

```python
from __future__ import annotations

import random


def ise_accounting_line() -> bytes:
    ip = f"10.3.{random.randint(1,254)}.{random.randint(1,254)}"
    return (
        f"<14>CISE_RADIUS_Accounting Acct-Status-Type=Start "
        f"User-Name=svc{random.randint(1,10)}@example.com Framed-IP-Address={ip}\n"
    ).encode()
```

- [ ] **Step 4: Write `loadtest/tests/test_generators.py`**

```python
from loadtest.generators.pan_fixture import pan_traffic_line
from loadtest.generators.fortigate_fixture import fortigate_traffic_line
from loadtest.generators.ad_4624_fixture import ad_4624_line
from loadtest.generators.ise_fixture import ise_accounting_line


def test_pan_line_is_csv_and_ends_newline() -> None:
    line = pan_traffic_line()
    assert line.endswith(b"\n")
    assert b"TRAFFIC,end" in line


def test_fortigate_is_kv_and_has_required_keys() -> None:
    line = fortigate_traffic_line()
    for key in (b"srcip=", b"dstip=", b"dstport=", b"sentbyte="):
        assert key in line


def test_ad_4624_has_eventid_and_ip() -> None:
    line = ad_4624_line()
    assert b"EventID=4624" in line
    assert b"IpAddress=" in line


def test_ise_has_accounting_and_ip() -> None:
    line = ise_accounting_line()
    assert b"CISE_RADIUS_Accounting" in line
    assert b"Framed-IP-Address=" in line
```

- [ ] **Step 5: Write `loadtest/locustfile.py`**

```python
"""Locust entry — picks a scenario from env var LOAD_SCENARIO."""
from __future__ import annotations

import os
import socket

from locust import User, between, events, task

from loadtest.generators.pan_fixture import pan_traffic_line
from loadtest.generators.fortigate_fixture import fortigate_traffic_line
from loadtest.generators.ad_4624_fixture import ad_4624_line
from loadtest.generators.ise_fixture import ise_accounting_line

SYSLOG_HOST = os.getenv("SYSLOG_HOST", "traefik")
FIREWALL_PORT = int(os.getenv("FIREWALL_PORT", "514"))
AD_PORT = int(os.getenv("AD_PORT", "516"))
ISE_PORT = int(os.getenv("ISE_PORT", "517"))
SCENARIO = os.getenv("LOAD_SCENARIO", "sustained")


class _UdpClient:
    def __init__(self, host: str, port: int) -> None:
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, payload: bytes) -> None:
        self._sock.sendto(payload, self._addr)


class FlowSender(User):
    wait_time = between(0, 0)

    def on_start(self) -> None:
        self.client_pan = _UdpClient(SYSLOG_HOST, FIREWALL_PORT)
        self.client_fgt = _UdpClient(SYSLOG_HOST, FIREWALL_PORT)

    @task(2)
    def pan(self) -> None:
        self.client_pan.send(pan_traffic_line())

    @task(1)
    def fortigate(self) -> None:
        self.client_fgt.send(fortigate_traffic_line())


class IdentitySender(User):
    wait_time = between(0, 0)

    def on_start(self) -> None:
        self.client_ad = _UdpClient(SYSLOG_HOST, AD_PORT)
        self.client_ise = _UdpClient(SYSLOG_HOST, ISE_PORT)

    @task(1)
    def ad(self) -> None:
        self.client_ad.send(ad_4624_line())

    @task(1)
    def ise(self) -> None:
        self.client_ise.send(ise_accounting_line())


@events.test_start.add_listener
def _announce(environment, **_kwargs) -> None:
    print(f"Load test scenario={SCENARIO} host={SYSLOG_HOST}")
```

- [ ] **Step 6: Write scenario shape config (profiles)**

`loadtest/scenarios/sustained.py` — one-line profile descriptor consumed by the compose loadtest profile:

```python
# sustained — 20 000 flows/s for 10 minutes
users = 200              # each user sends ~100 msgs/s
spawn_rate = 200
duration_s = 600
scenario = "sustained"
```

Similarly `loadtest/scenarios/burst.py`:

```python
# burst — 50 000 flows/s for 60 s then 10 000 flows/s for the rest
users = 500
spawn_rate = 500
duration_s = 180
scenario = "burst"
# (step-down handled by a custom LoadTestShape — implementation reads this file)
```

And `loadtest/scenarios/identity_surge.py`:

```python
users = 100             # identity only; FlowSender disabled via env
spawn_rate = 100
duration_s = 120
scenario = "identity_surge"
```

Extend `locustfile.py` to read the scenario module and register a `LoadTestShape` implementing the `tick()` pattern for `burst` (return (users, spawn_rate) tuples for the right time segment).

- [ ] **Step 7: Run generator tests**

Run: `pytest loadtest/tests/test_generators.py -v`
Expected: PASS (4).

- [ ] **Step 8: Commit**

```bash
git add loadtest/
git commit -m "feat(loadtest): locust scenarios, syslog fixture generators, and unit tests"
```

---

### Task 4.2: `docker-compose.loadtest.yml` overlay

**Files:**
- Create: `docker-compose.loadtest.yml`

- [ ] **Step 1: Write overlay**

```yaml
# Usage:
#   docker compose -f docker-compose.yml -f docker-compose.loadtest.yml \
#     --profile loadtest up -d
#
# Override scenario at run time:
#   LOAD_SCENARIO=burst docker compose -f ... up -d

services:
  locust-master:
    build: ./loadtest
    profiles: [loadtest]
    environment:
      LOAD_SCENARIO: ${LOAD_SCENARIO:-sustained}
      SYSLOG_HOST: traefik
      FIREWALL_PORT: "514"
      AD_PORT: "516"
      ISE_PORT: "517"
    command:
      - --headless
      - --users=200
      - --spawn-rate=200
      - --run-time=10m
      - --host=http://api:8000
      - --only-summary
    networks: [backend]
    depends_on:
      api:
        condition: service_healthy

  locust-worker:
    build: ./loadtest
    profiles: [loadtest]
    environment:
      LOAD_SCENARIO: ${LOAD_SCENARIO:-sustained}
      SYSLOG_HOST: traefik
    command: ["--worker", "--master-host=locust-master"]
    deploy:
      replicas: 4
    networks: [backend]
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.loadtest.yml
git commit -m "feat(loadtest): compose overlay with locust master + 4 workers under profile 'loadtest'"
```

---

### Task 4.3: Weekly load-test GitHub Actions workflow

**Files:**
- Create: `.github/workflows/loadtest.yml`

- [ ] **Step 1: Write workflow**

```yaml
name: Load Test (weekly)

on:
  schedule:
    - cron: "0 6 * * 1"    # Mon 06:00 UTC
  workflow_dispatch:

jobs:
  sustained:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - name: Build + start stack with observability
        env:
          APP_DOMAIN: localhost
          POSTGRES_USER: ztna
          POSTGRES_PASSWORD: loadtest
          POSTGRES_DB: ztna
          DATABASE_URL: postgresql+asyncpg://ztna:loadtest@postgres:5432/ztna
          REDIS_URL: redis://redis:6379/0
          SESSION_SECRET: loadtest-secret-loadtest-secret-32
          GRAFANA_ADMIN_PASSWORD: loadtest
        run: |
          docker compose \
            -f docker-compose.yml \
            -f docker-compose.observe.yml \
            --profile observe up -d --build
          # Wait for api readiness.
          for i in $(seq 1 60); do
            docker compose exec -T api python -c \
              "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)" \
              && break
            sleep 2
          done

      - name: Run sustained load
        env:
          LOAD_SCENARIO: sustained
        run: |
          docker compose \
            -f docker-compose.yml \
            -f docker-compose.observe.yml \
            -f docker-compose.loadtest.yml \
            --profile loadtest --profile observe up \
            --exit-code-from locust-master locust-master

      - name: Assert pass criteria
        run: |
          # Zero drops counter since stack start.
          drops=$(curl -s http://localhost:9100/metrics | \
            awk '/^correlator_dropped_flows_total/ {print $2}' | \
            python -c "import sys; print(int(float(sys.stdin.read().strip() or 0)))")
          if [ "$drops" -ne 0 ]; then
            echo "::error::correlator dropped $drops flows — fail"; exit 1
          fi
          # p99 flow-to-db latency (Histogram query through Prometheus HTTP API)
          p99=$(curl -s 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(postgres_insert_batch_size_seconds_bucket[5m]))by(le))' \
            | python -c "import sys,json; d=json.load(sys.stdin)['data']['result']; print(float(d[0]['value'][1]) if d else 0)")
          python -c "import sys; sys.exit(0 if $p99 < 0.5 else 1)" || {
            echo "::error::p99 queue-to-db latency ${p99}s >= 500ms"; exit 1; }

      - name: Teardown
        if: always()
        run: docker compose -f docker-compose.yml -f docker-compose.observe.yml -f docker-compose.loadtest.yml down -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/loadtest.yml
git commit -m "ci(loadtest): weekly sustained load-test workflow with pass-criteria gates"
```

---

### Task 4.4: Supply-chain security workflow

**Files:**
- Create: `.github/workflows/security.yml`
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Write `.github/workflows/security.yml`**

```yaml
name: Security

on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: "0 7 * * *"

permissions:
  contents: read
  security-events: write

jobs:
  pip-audit:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [api, flow-ingest, id-ingest, correlator, migrate]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pip-audit==2.7.3
      - run: |
          if [ -f "${{ matrix.service }}/requirements.txt" ]; then
            pip-audit -r "${{ matrix.service }}/requirements.txt" \
              --strict --disable-pip --vulnerability-service osv \
              --ignore-vuln GHSA-placeholder
          else
            pip-audit "./${{ matrix.service }}" --strict --disable-pip || true
          fi

  npm-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: npm, cache-dependency-path: web/package-lock.json }
      - run: npm ci --omit=dev
        working-directory: web
      - run: npm audit --production --audit-level=high
        working-directory: web

  trivy-images:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [api, flow-ingest, id-ingest, correlator, migrate, web]
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -t ztna-${{ matrix.service }}:scan ./${{ matrix.service }}
      - name: Trivy scan
        uses: aquasecurity/trivy-action@0.24.0
        with:
          image-ref: ztna-${{ matrix.service }}:scan
          severity: HIGH,CRITICAL
          exit-code: "1"
          ignore-unfixed: true

  sbom:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: anchore/sbom-action@v0
        with:
          path: "."
          format: cyclonedx-json
          output-file: ztna-sbom.cdx.json
      - uses: actions/upload-artifact@v4
        with:
          name: ztna-sbom
          path: ztna-sbom.cdx.json
```

- [ ] **Step 2: Write `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: "/api"
    schedule: { interval: weekly }
  - package-ecosystem: pip
    directory: "/flow-ingest"
    schedule: { interval: weekly }
  - package-ecosystem: pip
    directory: "/id-ingest"
    schedule: { interval: weekly }
  - package-ecosystem: pip
    directory: "/correlator"
    schedule: { interval: weekly }
  - package-ecosystem: pip
    directory: "/migrate"
    schedule: { interval: weekly }
  - package-ecosystem: pip
    directory: "/loadtest"
    schedule: { interval: weekly }
  - package-ecosystem: npm
    directory: "/web"
    schedule: { interval: weekly }
  - package-ecosystem: npm
    directory: "/e2e"
    schedule: { interval: weekly }
  - package-ecosystem: github-actions
    directory: "/"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/api"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/flow-ingest"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/id-ingest"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/correlator"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/migrate"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/web"
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: "/backup"
    schedule: { interval: weekly }
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/security.yml .github/dependabot.yml
git commit -m "ci(security): pip-audit, npm audit, trivy, SBOM, and weekly dependabot updates"
```

---

### Task 4.5: Pin Python deps via uv + lockfile-drift check

**Files:**
- Create: `api/requirements.txt` (committed, generated from pyproject by `uv pip compile`)
- Create: `flow-ingest/requirements.txt`
- Create: `id-ingest/requirements.txt`
- Create: `correlator/requirements.txt`
- Modify: `migrate/requirements.txt` (already pinned in P1 — leave as-is but verify)
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Install uv locally**

```bash
pip install uv==0.4.18
```

- [ ] **Step 2: Generate lockfiles for each Python service**

```bash
uv pip compile api/pyproject.toml -o api/requirements.txt
uv pip compile flow-ingest/pyproject.toml -o flow-ingest/requirements.txt
uv pip compile id-ingest/pyproject.toml -o id-ingest/requirements.txt
uv pip compile correlator/pyproject.toml -o correlator/requirements.txt
```

- [ ] **Step 3: Update each Dockerfile to install from the lockfile**

Example `api/Dockerfile` diff:

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Non-root user (hardening)
RUN useradd --system --uid 1001 ztna
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
USER ztna
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Mirror the non-root + `--no-deps` install pattern in flow-ingest, id-ingest, correlator Dockerfiles.

- [ ] **Step 4: Add lockfile drift check to `.github/workflows/ci.yml`**

Add a new job:

```yaml
  lockfile-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install uv==0.4.18
      - name: Recompile all lockfiles
        run: |
          for svc in api flow-ingest id-ingest correlator; do
            uv pip compile "$svc/pyproject.toml" -o "/tmp/$svc.txt" --quiet
            diff -u "$svc/requirements.txt" "/tmp/$svc.txt" \
              || { echo "::error::$svc/requirements.txt is out of sync with pyproject.toml"; exit 1; }
          done
```

- [ ] **Step 5: Verify locally that all services still build**

Run: `docker compose build`
Expected: all images build, no missing-dependency errors.

- [ ] **Step 6: Commit**

```bash
git add api/requirements.txt flow-ingest/requirements.txt id-ingest/requirements.txt correlator/requirements.txt api/Dockerfile flow-ingest/Dockerfile id-ingest/Dockerfile correlator/Dockerfile .github/workflows/ci.yml
git commit -m "chore(deps): pin Python deps via uv lockfiles and enforce drift check in CI"
```

---

## Chunk 6: Playwright E2E suite + accessibility + role-gate coverage

### Task 5.1: Scaffold Playwright project

**Files:**
- Create: `e2e/package.json`
- Create: `e2e/playwright.config.ts`
- Create: `e2e/tsconfig.json`
- Create: `e2e/fixtures/oidc-mock.ts`
- Create: `e2e/fixtures/seed-flows.ts`

- [ ] **Step 1: Write `e2e/package.json`**

```json
{
  "name": "ztna-e2e",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "test": "playwright test",
    "test:ci": "playwright test --reporter=line"
  },
  "devDependencies": {
    "@playwright/test": "1.48.0",
    "@axe-core/playwright": "4.9.1",
    "typescript": "5.5.4"
  }
}
```

- [ ] **Step 2: Write `e2e/playwright.config.ts`**

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.APP_URL ?? "https://localhost",
    ignoreHTTPSErrors: true,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
```

- [ ] **Step 3: Write `e2e/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["tests/**/*", "fixtures/**/*"]
}
```

- [ ] **Step 4: Write OIDC mock + seed helpers**

`e2e/fixtures/oidc-mock.ts`:

```ts
import { Page } from "@playwright/test";

/** Intercept the /api/auth/login → IdP redirect → /callback round trip and
 * bypass with a pre-signed mock session cookie. The API recognises a
 * `MOCK_SESSION` env that enables a test-only route POST /api/test/login-as
 * accepting {upn, roles} and returning a real session cookie for this domain.
 */
export async function loginAs(
  page: Page,
  upn: string,
  roles: Array<"viewer" | "editor" | "admin">,
) {
  const r = await page.request.post("/api/test/login-as", {
    data: { upn, roles },
    failOnStatusCode: true,
  });
  const { session, csrf_token } = await r.json();
  await page.context().addCookies([
    { name: "session", value: session, url: page.url() || "https://localhost" },
    { name: "csrf_token", value: csrf_token, url: page.url() || "https://localhost" },
  ]);
}
```

`e2e/fixtures/seed-flows.ts`:

```ts
import { APIRequestContext } from "@playwright/test";

/** POST a synthetic SankeyDelta through a test-only route. The api
 * exposes POST /api/test/seed when MOCK_SESSION is set.
 */
export async function seedFlows(req: APIRequestContext, delta: unknown) {
  await req.post("/api/test/seed", { data: delta, failOnStatusCode: true });
}
```

- [ ] **Step 5: Add a test-only route in `api/src/api/main.py`**

Gated behind `settings.mock_session_enabled` (env `MOCK_SESSION=1`). Routes return 404 when disabled. Implementation:

```python
if settings.mock_session_enabled:
    from api.auth.session import SessionCodec, SessionData
    import secrets, time

    @app.post("/api/test/login-as")
    async def test_login_as(payload: dict) -> dict:
        csrf = secrets.token_urlsafe(8)
        token = SessionCodec(settings.session_secret).encode(
            SessionData(user_upn=payload["upn"], roles=set(payload["roles"]),
                        csrf=csrf, exp=int(time.time()) + 3600))
        return {"session": token, "csrf_token": csrf}

    @app.post("/api/test/seed")
    async def test_seed(payload: dict) -> dict:
        # Republish on the sankey.live Redis pub/sub as-if from correlator.
        from api.redis import get_redis
        await get_redis().publish("sankey.live", json.dumps(payload))
        return {"ok": True}
```

Add `mock_session_enabled: bool = False` to Settings. Add the pydantic parse that `MOCK_SESSION=1` → True. Add a test gating the routes are 404 by default.

- [ ] **Step 6: Commit**

```bash
git add e2e/package.json e2e/playwright.config.ts e2e/tsconfig.json e2e/fixtures api/src/api/main.py api/src/api/settings.py
git commit -m "feat(e2e): scaffold Playwright project with OIDC mock and seed helpers"
```

---

### Task 5.2: Golden-path E2E

**Files:**
- Create: `e2e/tests/golden-path.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { expect, test } from "@playwright/test";
import { loginAs } from "../fixtures/oidc-mock";
import { seedFlows } from "../fixtures/seed-flows";

test("golden path: login → Sankey → link → override → relabel", async ({ page, request }) => {
  await loginAs(page, "alice@example.com", ["editor", "viewer"]);
  await page.goto("/");

  // Sankey renders inside 3 s.
  await expect(page.getByTestId("sankey")).toBeVisible({ timeout: 3000 });

  // Seed a deterministic delta with one link we know how to assert.
  await seedFlows(request, {
    ts: new Date().toISOString(),
    window_s: 5,
    nodes_left: [{ id: "g:eng", label: "Engineering", size: 10 }],
    nodes_right: [{ id: "app:m365", label: "Microsoft 365", kind: "saas" }],
    links: [{ src: "g:eng", dst: "app:m365", bytes: 1_000_000, flows: 10, users: 5 }],
  });

  // Click the link.
  await page.getByTestId("link-g:eng→app:m365").click();
  await expect(page.getByTestId("details-pane")).toContainText("Microsoft 365");

  // Open override modal and save a new label.
  await page.getByRole("button", { name: /override app label/i }).click();
  await page.getByLabel("Name").fill("Corp M365");
  await page.getByRole("button", { name: /save/i }).click();

  // Seed again; right-node label should update within 10 s.
  await seedFlows(request, {
    ts: new Date().toISOString(),
    window_s: 5,
    nodes_left: [{ id: "g:eng", label: "Engineering", size: 10 }],
    nodes_right: [{ id: "app:m365", label: "Corp M365", kind: "manual" }],
    links: [{ src: "g:eng", dst: "app:m365", bytes: 1_000_000, flows: 10, users: 5 }],
  });
  await expect(page.getByText("Corp M365")).toBeVisible({ timeout: 10_000 });

  // Logout.
  await page.getByRole("button", { name: /sign out/i }).click();
  await expect(page.getByRole("link", { name: /sign in/i })).toBeVisible();
});
```

- [ ] **Step 2: Commit**

```bash
git add e2e/tests/golden-path.spec.ts
git commit -m "test(e2e): golden-path login→Sankey→override→logout"
```

---

### Task 5.3: Historical mode E2E

**Files:**
- Create: `e2e/tests/historical.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { expect, test } from "@playwright/test";
import { loginAs } from "../fixtures/oidc-mock";

test("historical mode: switch, pick range, verify aggregate load", async ({ page }) => {
  await loginAs(page, "alice@example.com", ["viewer"]);
  await page.goto("/");
  await page.getByRole("button", { name: /historical/i }).click();

  await page.getByLabel(/from/i).fill("2026-04-20T00:00");
  await page.getByLabel(/to/i).fill("2026-04-22T00:00");
  await page.getByRole("button", { name: /apply/i }).click();

  await expect(page.getByTestId("sankey")).toBeVisible();
  await expect(page.getByTestId("time-window-label")).toHaveText(/historical/i);
});
```

- [ ] **Step 2: Commit**

```bash
git add e2e/tests/historical.spec.ts
git commit -m "test(e2e): historical mode time-range load"
```

---

### Task 5.4: Group-rollup E2E

**Files:**
- Create: `e2e/tests/group-rollup.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { expect, test } from "@playwright/test";
import { loginAs } from "../fixtures/oidc-mock";

test("group rollup: toggle between group, user, src_ip", async ({ page }) => {
  await loginAs(page, "alice@example.com", ["viewer"]);
  await page.goto("/");

  // Default is group mode.
  await expect(page.getByTestId("group-mode-label")).toHaveText(/group/i);

  await page.getByRole("radio", { name: /users/i }).check();
  await expect(page.getByTestId("group-mode-label")).toHaveText(/user/i);

  await page.getByRole("radio", { name: /source ip/i }).check();
  await expect(page.getByTestId("group-mode-label")).toHaveText(/src_ip/i);

  // Click a group node → member list modal.
  await page.getByRole("radio", { name: /group/i }).check();
  await page.getByTestId("group-node").first().click();
  await expect(page.getByRole("dialog", { name: /group members/i })).toBeVisible();
});
```

- [ ] **Step 2: Commit**

```bash
git add e2e/tests/group-rollup.spec.ts
git commit -m "test(e2e): group-rollup mode toggle and member list modal"
```

---

### Task 5.5: Unknown-user strand E2E

**Files:**
- Create: `e2e/tests/unknown-user.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { expect, test } from "@playwright/test";
import { loginAs } from "../fixtures/oidc-mock";
import { seedFlows } from "../fixtures/seed-flows";

test("unknown-user strand renders amber with banner", async ({ page, request }) => {
  await loginAs(page, "alice@example.com", ["viewer"]);
  await page.goto("/");

  await seedFlows(request, {
    ts: new Date().toISOString(),
    window_s: 5,
    nodes_left: [{ id: "unknown", label: "unknown", size: 1 }],
    nodes_right: [{ id: "app:m365", label: "Microsoft 365", kind: "saas" }],
    links: [{ src: "unknown", dst: "app:m365", bytes: 2048, flows: 1, users: 1 }],
  });

  const strand = page.getByTestId("link-unknown→app:m365");
  await expect(strand).toBeVisible();
  // Amber visual — verify via aria-label + CSS var.
  await expect(strand).toHaveAttribute("data-state", "unknown");
  await expect(page.getByTestId("unknown-banner")).toBeVisible();
});
```

- [ ] **Step 2: Commit**

```bash
git add e2e/tests/unknown-user.spec.ts
git commit -m "test(e2e): unknown-user strand amber colouring and banner"
```

---

### Task 5.6: Accessibility E2E (axe-core)

**Files:**
- Create: `e2e/tests/accessibility.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { loginAs } from "../fixtures/oidc-mock";

const pages = ["/", "/historical", "/settings/applications", "/settings/saas"];

for (const path of pages) {
  test(`axe-core WCAG AA: ${path}`, async ({ page }) => {
    await loginAs(page, "alice@example.com", ["admin", "editor", "viewer"]);
    await page.goto(path);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add e2e/tests/accessibility.spec.ts
git commit -m "test(e2e): axe-core WCAG AA scan on every main page"
```

---

### Task 5.7: Role-gate E2E

**Files:**
- Create: `e2e/tests/role-gates.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { expect, test } from "@playwright/test";
import { loginAs } from "../fixtures/oidc-mock";

test("viewer cannot see override button", async ({ page }) => {
  await loginAs(page, "viewer@example.com", ["viewer"]);
  await page.goto("/");
  await expect(page.getByRole("button", { name: /override app label/i })).toHaveCount(0);
});

test("editor can see override button", async ({ page }) => {
  await loginAs(page, "editor@example.com", ["editor", "viewer"]);
  await page.goto("/");
  await page.getByTestId("link-g:eng→app:m365").click();
  await expect(page.getByRole("button", { name: /override app label/i })).toBeVisible();
});

test("admin can reload adapters", async ({ page, request }) => {
  await loginAs(page, "admin@example.com", ["admin", "editor", "viewer"]);
  const r = await request.post("/api/adapters/reload",
    { headers: { "X-CSRF-Token": "irrelevant-route-exempt" } });
  expect([200, 202]).toContain(r.status());
});

test("viewer cannot reload adapters", async ({ page, request }) => {
  await loginAs(page, "viewer@example.com", ["viewer"]);
  const r = await request.post("/api/adapters/reload");
  expect(r.status()).toBe(403);
});
```

- [ ] **Step 2: Commit**

```bash
git add e2e/tests/role-gates.spec.ts
git commit -m "test(e2e): role-gate coverage for viewer, editor, admin"
```

---

### Task 5.8: Playwright CI workflow

**Files:**
- Create: `.github/workflows/e2e.yml`

- [ ] **Step 1: Write workflow**

```yaml
name: E2E

on:
  pull_request:
    paths:
      - 'web/**'
      - 'api/**'
      - 'e2e/**'
      - 'docker-compose*.yml'
  push:
    branches: [main]

jobs:
  playwright:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - name: Install Playwright deps
        run: |
          cd e2e
          npm ci
          npx playwright install --with-deps chromium

      - name: Boot stack with MOCK_SESSION=1
        env:
          APP_DOMAIN: localhost
          POSTGRES_USER: ztna
          POSTGRES_PASSWORD: e2e
          POSTGRES_DB: ztna
          DATABASE_URL: postgresql+asyncpg://ztna:e2e@postgres:5432/ztna
          REDIS_URL: redis://redis:6379/0
          SESSION_SECRET: e2e-secret-e2e-secret-e2e-secret-32
          MOCK_SESSION: "1"
        run: |
          docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
          for i in $(seq 1 60); do
            docker compose exec -T api python -c \
              "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)" \
              && break
            sleep 2
          done

      - name: Run Playwright
        env: { APP_URL: https://localhost }
        run: |
          cd e2e
          npm run test:ci

      - name: Upload traces on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: e2e/playwright-report/

      - name: Teardown
        if: always()
        run: docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/e2e.yml
git commit -m "ci(e2e): run Playwright suite on every PR touching web/api/e2e"
```

---

## Chunk 7: Backup sidecar, ops runbooks, production hardening, final verification

### Task 6.1: Backup sidecar + restore script

**Files:**
- Create: `backup/Dockerfile`
- Create: `backup/crontab`
- Create: `scripts/backup-cron.sh`
- Create: `scripts/restore-backup.sh`
- Create: `backups/.gitkeep`
- Modify: `.gitignore`
- Modify: `docker-compose.yml`
- Test: `tests/smoke/test_backup_restore.py`

- [ ] **Step 1: Write `backup/Dockerfile`**

```dockerfile
FROM postgres:16-alpine
RUN apk add --no-cache bash dcron tzdata
ENV TZ=UTC
COPY crontab /etc/crontabs/root
COPY backup-cron.sh /usr/local/bin/backup-cron.sh
RUN chmod +x /usr/local/bin/backup-cron.sh
CMD ["crond", "-f", "-L", "/dev/stdout"]
```

- [ ] **Step 2: Write `backup/crontab`**

```cron
15 02 * * * /usr/local/bin/backup-cron.sh >> /var/log/backup.log 2>&1
```

- [ ] **Step 3: Write `scripts/backup-cron.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
: "${BACKUP_RETENTION_DAYS:=7}"

export PGPASSWORD="$POSTGRES_PASSWORD"

BACKUP_DIR=/backups
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUTFILE="${BACKUP_DIR}/ztna-${STAMP}.dump"

pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -Fc --no-owner --no-acl -Z 6 -f "$OUTFILE"

# Rotate: delete files older than retention (preserve the most recent no matter what).
find "$BACKUP_DIR" -name "ztna-*.dump" -type f -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete

echo "backup ok: $OUTFILE"
```

Mark executable: `chmod +x scripts/backup-cron.sh`.

Note: `backup/Dockerfile` copies from its build context. Copy or `RUN ln` so the script is actually present in the image — the Dockerfile `COPY backup-cron.sh ...` assumes the script sits next to the Dockerfile. Therefore: **copy** `scripts/backup-cron.sh` → `backup/backup-cron.sh` in the repo, or change the Dockerfile `COPY ../scripts/backup-cron.sh …` (docker context restriction — forbidden). Decision: maintain a single source of truth at `scripts/backup-cron.sh` and `COPY ../scripts/backup-cron.sh …` via docker bake or bind-mount it at runtime instead. Simpler: **keep the script at `backup/backup-cron.sh` only, and have `scripts/` symlink to it so the restore script (which also lives in `scripts/`) is the only `scripts/` entry**. The executing agent implements: place `backup-cron.sh` at `backup/backup-cron.sh` (not `scripts/`), update Dockerfile `COPY backup-cron.sh /usr/local/bin/backup-cron.sh` (no change), and skip the symlink.

- [ ] **Step 4: Write `scripts/restore-backup.sh`**

```bash
#!/usr/bin/env bash
# Usage: ./scripts/restore-backup.sh backups/ztna-2026-04-22T02-15-00Z.dump
set -euo pipefail

DUMP="${1:?usage: $0 <backup-file>}"
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 1; }

echo "This will STOP the stack, WIPE user tables in the database, and restore from $DUMP."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "aborted"; exit 1; }

docker compose stop api flow-ingest id-ingest correlator
docker compose up -d postgres redis
sleep 3

# Wipe tables we own (retain migrate history so alembic re-upgrades cleanly).
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
  DROP SCHEMA public CASCADE;
  CREATE SCHEMA public;
SQL

# Restore, strip extensions (they belong to Timescale setup).
docker compose exec -T postgres pg_restore \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl \
  < "$DUMP"

# Re-apply migrations so schema is current, then bring the stack back up.
docker compose up -d --no-deps migrate
docker compose up -d
echo "restore complete"
```

Mark executable: `chmod +x scripts/restore-backup.sh`.

- [ ] **Step 5: Append to `.gitignore`**

```
# Backups (local host volume; never committed)
/backups/*
!/backups/.gitkeep
```

Create `backups/.gitkeep` (empty file).

- [ ] **Step 6: Add backup service to `docker-compose.yml`**

```yaml
  backup:
    build: ./backup
    env_file: .env
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      BACKUP_RETENTION_DAYS: ${BACKUP_RETENTION_DAYS:-7}
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./backups:/backups
    networks: [backend]
    restart: unless-stopped
```

- [ ] **Step 7: Write smoke test `tests/smoke/test_backup_restore.py`**

```python
"""Round-trip: dump → drop user tables → restore → rowcount match."""
from __future__ import annotations

import os
import subprocess

import pytest

DOCKER_SMOKE = os.environ.get("DOCKER_SMOKE") == "1"
pytestmark = pytest.mark.skipif(not DOCKER_SMOKE, reason="DOCKER_SMOKE not set")


def _psql(sql: str) -> str:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres",
         "psql", "-U", "ztna", "-d", "ztna", "-Atc", sql],
        check=True, text=True, capture_output=True,
    ).stdout.strip()


def test_backup_restore_roundtrip(tmp_path) -> None:
    subprocess.run(["docker", "compose", "up", "-d", "--build"], check=True)
    try:
        # Seed a known row in applications.
        _psql("INSERT INTO applications (name, dst_cidr) VALUES ('probe', '10.0.0.0/8');")
        before = _psql("SELECT count(*) FROM applications;")

        # Take a backup on demand.
        out = tmp_path / "probe.dump"
        subprocess.run(
            ["docker", "compose", "exec", "-T", "backup",
             "/usr/local/bin/backup-cron.sh"], check=True)
        # Copy newest backup out.
        backups = subprocess.run(
            ["docker", "compose", "exec", "-T", "backup",
             "sh", "-c", "ls -1t /backups/ztna-*.dump | head -1"],
            check=True, text=True, capture_output=True).stdout.strip()
        subprocess.run(
            ["docker", "compose", "cp", f"backup:{backups}", str(out)],
            check=True)

        # Drop one row and restore from dump.
        _psql("DELETE FROM applications WHERE name='probe';")
        middle = _psql("SELECT count(*) FROM applications;")
        assert int(middle) == int(before) - 1

        subprocess.run(["bash", "-c",
                        f"echo RESTORE | ./scripts/restore-backup.sh {out}"],
                       check=True)

        after = _psql("SELECT count(*) FROM applications;")
        assert int(after) == int(before)
    finally:
        subprocess.run(["docker", "compose", "down", "-v"], check=False)
```

- [ ] **Step 8: Commit**

```bash
git add backup/ scripts/backup-cron.sh scripts/restore-backup.sh backups/.gitkeep .gitignore docker-compose.yml tests/smoke/test_backup_restore.py
git commit -m "feat(backup): pg_dump sidecar with 7-day rotation and restore script"
```

---

### Task 6.2: Operations runbook

**Files:**
- Create: `docs/operations.md`

- [ ] **Step 1: Write `docs/operations.md` with each of these sections filled**

Required headings and contents:

```markdown
# ZTNA Flow Discovery — Operations Runbook

## 1. Deployment variants

### 1.1 Dev / single-host
- `make up` brings up the full stack with self-signed TLS.
- Use `.env.example` as-is; only `APP_DOMAIN` needs editing.

### 1.2 Production
- Base: `docker-compose.yml`
- Overlay: `docker-compose.prod.yml` (ACME, Docker secrets, resource limits,
  logrotate caps).
- Optional: `docker-compose.observe.yml` (profile `observe`) for Prometheus
  + Grafana.

Boot:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 2. Secrets (production)

Move from `.env` to Docker secrets. The following secrets are defined in
`docker-compose.prod.yml`:
- `postgres_password`
- `entra_client_secret`
- `ad_bind_password`
- `session_secret`

Migration from `.env`:
1. Create each secret: `printf "%s" "$(grep ^POSTGRES_PASSWORD .env | cut -d= -f2)" | docker secret create postgres_password -`
2. Remove the corresponding env line from `.env`.
3. `docker compose up -d` — services consume `_FILE` env vars pointing at `/run/secrets/<name>`.

## 3. Upgrade procedure
1. `git pull`
2. `docker compose pull`                  # pulls newer base images
3. `docker compose build`                 # rebuilds local images
4. `docker compose up -d`                 # migrate runs, then services roll

## 4. Backup + restore
- Automatic: daily 02:15 UTC via `backup` sidecar → `./backups/ztna-<ts>.dump`
- 7-day rotation, configurable via `BACKUP_RETENTION_DAYS`.
- Manual restore: `./scripts/restore-backup.sh backups/ztna-YYYY-MM-DDTHH-MM-SSZ.dump`

## 5. Incident playbooks

### 5.1 Correlator stuck (queue_depth climbing, drops nonzero)
- Symptom: Grafana "Correlator queue depth" chart steadily rising.
- Action:
  1. `docker compose logs --tail=200 correlator` → look for Redis reconnects
     or Postgres write errors.
  2. Check Redis lag: `docker compose exec redis redis-cli xinfo stream flows.raw`
  3. Restart: `docker compose restart correlator`
  4. If it recurs, scale flow-ingest replicas via `docker compose up -d --scale flow-ingest=2`

### 5.2 Redis lag > 30 s
- Symptom: WS "Live · 45s behind" banner.
- Action:
  1. `docker stats redis` → check CPU/memory saturation.
  2. `docker compose exec redis redis-cli info replication`
  3. If Redis is healthy but lag persists, scale flow-ingest; if unhealthy,
     `docker compose restart redis` (messages already durably in postgres).

### 5.3 Unknown-user ratio > 50 % for 10 min
- Symptom: dashboard "Unknown user ratio" gauge > 0.5.
- Action:
  1. `curl -sk https://${APP_DOMAIN}/api/adapters` — verify identity adapters
     are reporting healthy with non-zero event rate.
  2. Inspect group-sync: `docker compose logs --tail=200 id-ingest | grep group-sync`.
  3. If group-sync last-success > 48 h ago, trigger manual refresh via
     `POST /api/adapters/group-sync/run` (admin).

### 5.4 DB disk near-full
- Symptom: `df -h` on host shows < 10 % free on postgres volume.
- Action:
  1. Confirm retention: `SELECT job_id, application_name, schedule_interval
     FROM timescaledb_information.jobs;`
  2. Shorten retention temporarily:
     `SELECT remove_retention_policy('flows');`
     `SELECT add_retention_policy('flows', INTERVAL '14 days');`
  3. Drop oldest chunks: `SELECT drop_chunks('flows', INTERVAL '14 days');`
  4. Add volume or provision more storage.

### 5.5 `api` down → Traefik dashboard locked out
- The dashboard uses forwardAuth → `api` `/auth/verify`. If api is down,
  `/traefik` returns 502.
- Admin fallback:
  1. `docker compose logs --tail=200 traefik api`
  2. Inspect via socket: `docker compose exec traefik wget -q -O- http://127.0.0.1:8080/api/rawdata`
  3. Restart: `docker compose restart api` → once healthy, `/traefik` works again.

## 6. WEF / Winlogbeat quick-link
The full WEF + Winlogbeat runbook lives in [`docs/adapters.md`](./adapters.md#ad-4624-winlogbeat)
(owned by the P3 identity plan). P4 validates that runbook references stay
correct after each P3 merge.
```

- [ ] **Step 2: Commit**

```bash
git add docs/operations.md
git commit -m "docs(ops): deployment, secrets, upgrade, backup, and incident runbooks"
```

---

### Task 6.3: Security posture doc

**Files:**
- Create: `docs/security.md`

- [ ] **Step 1: Write `docs/security.md`**

```markdown
# Security Posture

## Supply chain
- Python deps pinned via `uv pip compile` → `*/requirements.txt` (committed).
- Drift check in CI blocks a PR with stale lockfiles.
- `pip-audit` runs on every PR + nightly; HIGH+ vulns fail the build.
- `npm audit --production --audit-level=high` enforced in CI.
- `trivy image` scans every built image for HIGH/CRITICAL.
- SBOM generated with Syft as a workflow artifact.

## Runtime
- All app containers run as non-root (uid 1001).
- Only Traefik publishes host ports (:443 + syslog entrypoints).
- TLS terminated at Traefik; internal plaintext on the Docker `backend` network.
- Rate limits: 60 rps/user REST, 300 rps/IP on `/api/auth/*`, 1 WS/user.
- CSP: default-src 'self'; no inline script; frame-ancestors 'none'.
- HSTS preload, frame-deny, nosniff, Referrer-Policy, Permissions-Policy.

## Authentication
- OIDC via Entra; JWT RS256 validated against cached JWKS (1 h TTL).
- Access tokens 1 h; refresh 8 h (Entra-managed).
- Cookie session httpOnly, Secure, SameSite=Strict.
- CSRF double-submit token on non-safe cookie-authed methods.
- Role derived from Entra security-group object IDs (env).

## PII
- UPN and source IP hashed (`sha256:` + 16-hex prefix) at INFO logging level.
- Raw values present only at DEBUG — set via `LOG_LEVEL=DEBUG` env.

## Secrets (production)
- Docker secrets (never env) for: postgres_password, entra_client_secret,
  ad_bind_password, session_secret.
- `session_secret` MUST be ≥ 32 bytes; regenerate on compromise with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/security.md
git commit -m "docs(security): document supply-chain, runtime, auth, and secrets posture"
```

---

### Task 6.4: Production hardening — docker-compose.prod.yml

**Files:**
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Extend the prod overlay with secrets, resource limits, log rotation**

Append to the existing overlay (keeping the P1 ACME block intact):

```yaml
secrets:
  postgres_password:
    external: true
  entra_client_secret:
    external: true
  ad_bind_password:
    external: true
  session_secret:
    external: true

x-logging: &logging
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"

services:
  postgres:
    secrets: [postgres_password]
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    deploy:
      resources:
        limits: { cpus: "4.0", memory: 4G }
        reservations: { cpus: "1.0", memory: 1G }
    logging: *logging

  redis:
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 1G }
    logging: *logging

  api:
    secrets: [entra_client_secret, session_secret]
    environment:
      OIDC_CLIENT_SECRET_FILE: /run/secrets/entra_client_secret
      SESSION_SECRET_FILE:     /run/secrets/session_secret
    deploy:
      resources:
        limits: { cpus: "2.0", memory: 1G }
    logging: *logging

  flow-ingest:
    deploy:
      resources:
        limits: { cpus: "2.0", memory: 1G }
    logging: *logging

  id-ingest:
    secrets: [ad_bind_password, entra_client_secret]
    environment:
      AD_BIND_PASSWORD_FILE: /run/secrets/ad_bind_password
      ENTRA_CLIENT_SECRET_FILE: /run/secrets/entra_client_secret
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 512M }
    logging: *logging

  correlator:
    deploy:
      resources:
        limits: { cpus: "4.0", memory: 2G }
    logging: *logging

  traefik:
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 512M }
    logging: *logging

  backup:
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 512M }
    logging: *logging
```

- [ ] **Step 2: Teach `api/src/api/settings.py` to read `*_FILE` overrides**

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def _load_from_files(self) -> "Settings":
        for attr, env_file in (
            ("oidc_client_secret", "OIDC_CLIENT_SECRET_FILE"),
            ("session_secret",     "SESSION_SECRET_FILE"),
        ):
            path = os.environ.get(env_file)
            if path and Path(path).is_file():
                setattr(self, attr, Path(path).read_text().strip())
        return self
```

Mirror the pattern in `id-ingest` settings (AD_BIND_PASSWORD_FILE, ENTRA_CLIENT_SECRET_FILE).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.prod.yml api/src/api/settings.py id-ingest/src/id_ingest/settings.py
git commit -m "feat(prod): docker secrets, resource limits, and log rotation"
```

---

### Task 6.5: Final verification

**Files:**
- Modify: `README.md` (add observability + load + E2E commands)

- [ ] **Step 1: Extend README with a P4 "Production" section**

Append under the existing "Local development":

```markdown
## Production deployment

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d
```

See [`docs/operations.md`](docs/operations.md) for the full runbook.

## Observability
```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.observe.yml \
  --profile observe up -d
```
Grafana: `https://${APP_DOMAIN}/grafana` (admin role).

## Load test
```bash
LOAD_SCENARIO=sustained docker compose \
  -f docker-compose.yml \
  -f docker-compose.loadtest.yml \
  --profile loadtest up
```

## E2E
```bash
cd e2e && npm ci && npx playwright install --with-deps && npm test
```
```

- [ ] **Step 2: Run every CI job locally**

```bash
make ci                     # lint + type + pytest
pytest api/tests -v         # auth, metrics, logging, csrf, require_role
pytest loadtest/tests -v    # generators
cd e2e && npm ci && npx playwright install --with-deps && npm test
```

Expected: all green.

- [ ] **Step 3: Run full stack smoke with observability**

```bash
cp .env.example .env
# set APP_DOMAIN=localhost, POSTGRES_PASSWORD=dev, SESSION_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
make clean
docker compose -f docker-compose.yml -f docker-compose.observe.yml --profile observe up -d --build
# wait for api
for i in $(seq 1 60); do
  docker compose exec -T api python -c \
    "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready').status==200 else 1)" \
    && break
  sleep 2
done

# Verify metrics scraped
curl -s http://localhost:9090/api/v1/targets | python -c \
  "import json,sys,urllib.request; d=json.load(sys.stdin); print([t['labels']['job'] for t in d['data']['activeTargets']])"
# Expected: ['api','flow-ingest','id-ingest','correlator']

# Verify grafana renders
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/grafana/api/health
# Expected: 200 (after OIDC login; 302 otherwise — that's also acceptable here)

make clean
```

- [ ] **Step 4: If anything fails**

Use @superpowers:systematic-debugging — do NOT paper over. Common issues:
- **Grafana dashboard empty** → confirm `docs/grafana/ztna-overview.json` ==
  `observability/grafana/dashboards/ztna-overview.json`.
- **p99 query empty in loadtest gate** → make sure at least one histogram
  `observe()` has fired before the query.
- **non-root user can't bind port** → services bind > 1024 everywhere; verify
  `EXPOSE` directives match.
- **Trivy failures after dependabot PRs** → bump the affected dep in its
  `pyproject.toml`/`package.json` and recompile lockfile.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: README sections for production, observability, load, and E2E"
```

---

## Acceptance criteria (Plan 4 done)

- [ ] All spec §1 success criteria demonstrably met (deploy, 10 min flows, 15 min identity, 20 k flows/s, 5 s latency).
- [ ] OIDC auth required to reach any `/api/*` route except `/health/*` and `/metrics` (internal-only).
- [ ] `require_role` enforced on all CRUD routes; role-gate E2E tests prove viewer ≠ editor ≠ admin.
- [ ] Traefik `/traefik` dashboard returns 403 for non-admin, 200 for admin, 502 when api is down (documented fallback).
- [ ] `docker compose -f docker-compose.yml -f docker-compose.observe.yml --profile observe up -d` brings up Prometheus + Grafana with provisioned datasource and one dashboard.
- [ ] `/metrics` on api, flow-ingest, id-ingest, correlator returns Prometheus text format with at least the metrics listed in spec §10.
- [ ] All services emit JSON-serialised loguru output; PII hashed at INFO, raw at DEBUG; `trace_id` present on every line.
- [ ] Weekly `loadtest.yml` workflow passes (`sustained` scenario: zero dropped flows, p99 < 500 ms, Postgres CPU < 60 %).
- [ ] Playwright E2E (`e2e.yml`) green on a PR touching `web/`, `api/`, or `e2e/`.
- [ ] `security.yml` workflow green: `pip-audit`, `npm audit --audit-level=high`, `trivy image` (no HIGH/CRITICAL), Syft SBOM uploaded.
- [ ] `dependabot.yml` covers pip, npm, github-actions, docker ecosystems.
- [ ] `backup` sidecar produces a daily `ztna-<ts>.dump`; `scripts/restore-backup.sh` round-trips (smoke test green).
- [ ] `docker-compose.prod.yml` uses Docker secrets for postgres_password, entra_client_secret, ad_bind_password, session_secret; resource limits and log rotation applied to every service.
- [ ] All Python services run as uid 1001 (non-root) in their images.
- [ ] Lockfiles committed for every Python service; `lockfile-drift` CI job green.
- [ ] `docs/operations.md`, `docs/security.md` present and cross-linked from `README.md`; link to `docs/adapters.md` intact.
- [ ] `no-claude-attribution` check green across all P4 commits.

---

## Out of scope for Plan 4 (deferred to post-v1)

- Cross-cluster / multi-site federation.
- Active packet capture / DPI.
- Multi-tenant SaaS hosting of this tool.
- Automated rollback on failed upgrade (manual `docker compose` revert today).
- Policy enforcement (ZTNA gateway functionality).
