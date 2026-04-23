# ZTNA Flow Discovery — Operations Runbook

## 1. Deployment variants

### 1.1 Dev / single-host

- `make up` brings up the full stack with Traefik's built-in self-signed TLS.
- Use `.env.example` as-is; edit only `APP_DOMAIN` (default `ztna.example.com`).

### 1.2 Production

- Base: `docker-compose.yml`
- Overlay: `docker-compose.prod.yml` (ACME Let's Encrypt, Docker secrets, resource limits, log rotation)
- Optional: `docker-compose.observe.yml` (profile `observe`) for Prometheus + Grafana

Boot:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 2. Secrets (production)

In production, move the following from `.env` to Docker secrets:

- `postgres_password`
- `entra_client_secret`
- `ad_bind_password`
- `session_secret` (must be ≥ 32 bytes — regenerate via `python -c 'import secrets; print(secrets.token_urlsafe(32))'`)

Migration from `.env`:

1. Create each secret, e.g.

   ```bash
   grep ^POSTGRES_PASSWORD .env | cut -d= -f2- \
     | docker secret create postgres_password -
   ```

2. Remove the corresponding env line from `.env`.
3. `docker compose up -d` — services consume `_FILE` env vars pointing at `/run/secrets/<name>` (wired in `docker-compose.prod.yml`).

## 3. Upgrade procedure

1. `git pull`
2. `docker compose pull` — pulls newer base images
3. `docker compose build` — rebuilds local images
4. `docker compose up -d` — `migrate` runs first, then services roll over

## 4. Backup + restore

- **Automatic:** the `backup` sidecar runs `pg_dump -Fc` daily at 02:15 UTC → `./backups/ztna-<ts>.dump`.
- **Retention:** 7 days (configurable via `BACKUP_RETENTION_DAYS`).
- **Manual restore:**

  ```bash
  ./scripts/restore-backup.sh backups/ztna-YYYY-MM-DDTHH-MM-SSZ.dump
  ```

  The script stops app services, wipes `public`, runs `pg_restore`, re-applies migrations via the `migrate` sidecar, then brings the stack back up. Prompts for `RESTORE` to confirm.

## 5. Incident playbooks

### 5.1 Correlator stuck (queue depth climbing, drops nonzero)

Symptom: Grafana "Correlator queue depth" steadily rises; `correlator_dropped_flows_total` increments.

1. `docker compose logs --tail=200 correlator` → look for Redis reconnects or Postgres write errors.
2. Check Redis lag: `docker compose exec redis redis-cli xinfo stream flows.raw`
3. Restart: `docker compose restart correlator`
4. If recurrent, scale flow-ingest: `docker compose up -d --scale flow-ingest=2`.

### 5.2 Redis lag > 30 s

Symptom: WS "Live · 45s behind" banner.

1. `docker stats redis` → check CPU/memory.
2. `docker compose exec redis redis-cli info replication`
3. If Redis is healthy but lag persists, scale flow-ingest; if unhealthy, `docker compose restart redis` (flows already durable in postgres).

### 5.3 Unknown-user ratio > 50 % for 10 min

Symptom: dashboard "Unknown user ratio" gauge > 0.5; UI amber banner.

1. `curl -sk https://${APP_DOMAIN}/api/adapters` — identity adapters healthy with non-zero event rate?
2. `docker compose logs --tail=200 id-ingest | grep group-sync`
3. `GET /api/stats` → `group_sync_age_seconds` — if > 48 h, group-sync is stalled.
4. Admin can trigger on-demand refresh (P4-followup endpoint).

### 5.4 DB disk near-full

Symptom: `df -h` on host shows < 10 % free on the postgres volume.

1. Confirm retention:

   ```sql
   SELECT job_id, application_name, schedule_interval
     FROM timescaledb_information.jobs;
   ```

2. Shorten retention temporarily:

   ```sql
   SELECT remove_retention_policy('flows');
   SELECT add_retention_policy('flows', INTERVAL '14 days');
   ```

3. Drop old chunks: `SELECT drop_chunks('flows', INTERVAL '14 days');`
4. Provision more storage.

### 5.5 `api` down → Traefik dashboard locked out

The `/traefik` dashboard uses forwardAuth to `api`. If api is down, the dashboard returns 502.

1. `docker compose logs --tail=200 traefik api`
2. `docker compose exec traefik wget -q -O- http://127.0.0.1:8080/api/rawdata` for internal state.
3. `docker compose restart api` — once healthy, `/traefik` is reachable again.

## 6. Identity source runbooks

Per-adapter setup (WEF + Winlogbeat, Entra app registration, Cisco ISE LiveLogs, Aruba ClearPass CEF) lives in [`adapters.md`](./adapters.md). Confidence ranking, TTL semantics, and the LCD algorithm are in [`identity-model.md`](./identity-model.md).

## 7. Observability

Bring Prometheus + Grafana up with the `observe` profile:

```bash
make observe
```

Grafana is reachable at `https://${APP_DOMAIN}/grafana` behind the same OIDC forwardAuth that gates `/traefik` (admin role). Datasource + dashboards are provisioned at startup from `observability/grafana/`.

## 8. Load testing

```bash
LOAD_SCENARIO=sustained docker compose \
  -f docker-compose.yml \
  -f docker-compose.loadtest.yml \
  --profile loadtest up
```

Scenario files in `loadtest/scenarios/`. The weekly GitHub Action (`.github/workflows/loadtest.yml`) runs `sustained` against an ephemeral stack and fails the job on non-zero correlator drops.
