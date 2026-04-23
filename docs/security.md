# Security Posture

## Supply chain

- Python deps pinned per service in `pyproject.toml`. Lockfile generation
  (`uv pip compile`) and CI drift check are planned as a P4-followup task.
- `pip-audit` runs on every PR + nightly via `.github/workflows/security.yml`;
  HIGH+ vulnerabilities fail the job.
- `npm audit --production --audit-level=high` enforced on the web lockfile.
- `trivy image` scans every built container image; HIGH/CRITICAL findings
  fail the job.
- SBOM generated with Syft (CycloneDX JSON) and uploaded as a workflow
  artifact on every run.
- Dependabot updates pip, npm, github-actions, and docker ecosystems weekly
  (`.github/dependabot.yml`).

## Runtime

- Only Traefik publishes host ports (`:443` + syslog entrypoints `:514`,
  `:516`, `:517`, `:518`). All other services bind the internal `backend`
  Docker network exclusively.
- TLS terminates at Traefik; internal hop is plaintext on `backend`.
- Rate limits:
  - 60 rps/IP on authenticated REST (`rate-limit-api` middleware)
  - 300 rps/IP on `/api/auth/*` (`rate-limit-auth`)
  - 1 WS/user planned (see ws.py TODO(P4-followup))
- CSP: `default-src 'self'; script-src 'self'; frame-ancestors 'none'` and
  friends; HSTS preload; frame-deny; nosniff; Referrer-Policy; Permissions-
  Policy (camera, microphone, geolocation, payment disabled).
- `api` container should run as uid 1001 (non-root) — pending Dockerfile
  hardening in P4-followup.

## Authentication & RBAC

- OIDC via Entra ID; JWT RS256 validated against a cached JWKS (1 h TTL
  with kid-miss refresh).
- Access tokens 1 h; refresh 8 h (Entra-managed).
- Cookie session: `httpOnly`, `Secure`, `SameSite=Strict`; signed by
  `itsdangerous.URLSafeTimedSerializer` under `SESSION_SECRET` (≥ 32 bytes).
- CSRF: double-submit-token on non-safe cookie-authed methods (`X-CSRF-Token`
  header must match `csrf_token` cookie). Bearer-token flows exempt.
- Role derivation: Entra security-group object IDs mapped via
  `OIDC_GROUP_IDS_{ADMIN,EDITOR,VIEWER}` env vars. Hierarchy: admin ⊇
  editor ⊇ viewer.
- `require_role` FastAPI dependency enforced on every CRUD route. `/traefik`
  dashboard additionally requires `admin` via forwardAuth → `/auth/verify`.

## PII

- `upn`, `src_ip`, `user_upn`, `ip` in log records are hashed
  (`sha256:<16-hex>`) at INFO/WARNING/ERROR/CRITICAL levels.
- Raw values appear only at DEBUG (enable via `LOG_LEVEL=DEBUG`).
- `trace_id` from W3C `traceparent` is propagated to every log line on the
  same task.

## Secrets (production)

- Docker secrets (never env) wired in `docker-compose.prod.yml` for:
  `postgres_password`, `entra_client_secret`, `ad_bind_password`,
  `session_secret`.
- `session_secret` regeneration on compromise:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

  Rotating this secret invalidates all live cookie sessions (users are
  forced to re-authenticate).

## Test-only routes

- `POST /api/test/login-as` and `POST /api/test/seed` exist only when the
  api is started with `MOCK_SESSION=1`. They mint session cookies and
  publish synthetic SankeyDeltas for Playwright E2E; they are unreachable
  (404) in production.
- Unit test `api/tests/test_mock_session_routes.py` asserts 404 without the
  flag and 200 with it; any future code that conditionally mounts these
  routes should keep that test green.
