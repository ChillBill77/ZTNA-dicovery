# ZTNA Flow Discovery

Self-hosted near-realtime Sankey visualization of network flows, enriched with user and group identity from Entra ID / AD / Cisco ISE / Aruba ClearPass.

See the design spec: [`docs/superpowers/specs/2026-04-22-ztna-flow-discovery-design.md`](docs/superpowers/specs/2026-04-22-ztna-flow-discovery-design.md).

## Local development

### Prerequisites
- Docker 24+ / Docker Compose v2
- GNU Make
- Python 3.12 (for running tests outside the stack)

### Boot the stack

```bash
cp .env.example .env
# edit .env — at minimum set APP_DOMAIN, POSTGRES_PASSWORD

make up
```

This brings up: `traefik`, `postgres`, `redis`, `migrate` (runs once, applies Alembic migrations), `api` (health endpoints only in P1).

### Verify

```bash
docker compose ps
# api should be "healthy"

# `api` image is python:3.12-slim (no curl). Use python inline:
docker compose exec api python -c \
  "import urllib.request,sys; print(urllib.request.urlopen('http://localhost:8000/health/ready').read().decode())"
# JSON: {"status":"ok","components":{"db":true,"redis":true}}
```

### Tear down

```bash
make down            # keeps data volumes
make clean           # drops data volumes too
```

### Run tests

```bash
make test            # unit + integration (no Docker)
DOCKER_SMOKE=1 pytest tests/smoke -v   # full stack smoke test
```

---

## Production deployment

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d
```

Prod overlay adds: Let's Encrypt ACME, per-service resource limits, json-file log rotation (50MB × 5 rolls). Docker-secrets wiring for `postgres_password` / `entra_client_secret` / `ad_bind_password` / `session_secret` is stubbed behind a `secrets` block (full `_FILE` env plumbing is a P4-followup).

See [`docs/operations.md`](docs/operations.md) for the full runbook (deployment variants, secrets, upgrade, backup, incident playbooks).

## Observability

```bash
make observe
```

Brings Prometheus + Grafana up behind Traefik's OIDC forwardAuth (admin role). Grafana at `https://${APP_DOMAIN}/grafana`. Dashboard + datasource provisioned from `observability/grafana/`.

## Load test

```bash
LOAD_SCENARIO=sustained docker compose \
  -f docker-compose.yml \
  -f docker-compose.loadtest.yml \
  --profile loadtest up
```

Three scenarios in `loadtest/scenarios/`: `sustained` (20k flows/s × 10 min), `burst`, `identity_surge`. Weekly CI in `.github/workflows/loadtest.yml`.

## E2E

```bash
cd e2e
npm install
npx playwright install --with-deps chromium
MOCK_SESSION=1 npm test
```

Playwright fixtures (`e2e/fixtures/oidc-mock.ts`, `e2e/fixtures/seed-flows.ts`) mint session cookies and publish synthetic deltas via the `MOCK_SESSION`-gated `/api/test/*` routes. CI: `.github/workflows/e2e.yml`.

## Security

See [`docs/security.md`](docs/security.md) for supply-chain, runtime, auth, PII, and secrets posture.

Supply-chain scans (`pip-audit`, `npm audit`, `trivy`, Syft SBOM) run in `.github/workflows/security.yml`; weekly Dependabot bumps via `.github/dependabot.yml`.

---

# GitHub Actions – Workflow Documentation

This repository uses a set of GitHub Actions workflows to automate notifications, validate infrastructure changes, and enforce merge quality gates.

---

## Table of Contents

- [Workflows Overview](#workflows-overview)
- [Prerequisites](#prerequisites)
- [Workflow: Notify Teams on New Issue](#workflow-notify-teams-on-new-issue)
- [Workflow: Notify Teams on Pull Request Activity](#workflow-notify-teams-on-pull-request-activity)
- [Workflow: Validate Docker Compose](#workflow-validate-docker-compose)
- [Branch Protection Setup](#branch-protection-setup)
- [Secrets Reference](#secrets-reference)

---

## Workflows Overview

| File | Trigger | Blocks Merge | Teams Notification |
|---|---|---|---|
| `notify-teams-on-issue.yml` | Issue opened | No | ✅ Always |
| `notify-teams-on-pr.yml` | PR opened / closed / merged / review requested | No | ✅ Always |
| `validate-docker-compose.yml` | PR touching `docker-compose*.yml` or `.env*` | ✅ On lint or smoke test failure | ✅ On failure or warning |

---

## Prerequisites

### 1. Webhook Bot for Microsoft Teams

All Teams notifications are delivered via [Webhook Bot by C-Toss](https://www.c-toss.com/webhook-bot/), a modern replacement for the deprecated Microsoft 365 Incoming Webhook connector.

**Setup steps:**

1. Install [Webhook Bot](https://appsource.microsoft.com/en-us/product/office/WA200007770) from Microsoft AppSource into your Teams workspace
2. In the target Teams channel, open the Webhook Bot app and click **Create** to generate a webhook URL
3. Copy the URL — it will look like:
   ```
   https://webhookbot.c-toss.com/api/bot/webhooks/<your-uuid>
   ```
4. Add it as a GitHub secret (see [Secrets Reference](#secrets-reference))

> **Security note:** treat your webhook URL as a secret. If it is ever exposed, generate a new one in Teams and update the GitHub secret immediately.

### 2. GitHub Repository Secrets

Go to **Settings → Secrets and variables → Actions** and add the following:

| Secret | Description |
|---|---|
| `MS_TEAMS_WEBHOOK_URI` | Full webhook URL from Webhook Bot |

### 3. Workflow Permissions

For the Docker Compose workflow to post comments on pull requests, ensure GitHub Actions has write permissions:

**Settings → Actions → General → Workflow permissions → Read and write permissions** ✅

---

## Workflow: Notify Teams on New Issue

**File:** `.github/workflows/notify-teams-on-issue.yml`

Sends a Teams notification whenever a new issue is opened in the repository.

### Trigger

```yaml
on:
  issues:
    types: [opened]
```

### Teams Card

Sends an Adaptive Card containing:
- Issue number and title
- Opened by (GitHub username)
- Repository name
- Labels (if any)
- **"View Issue"** button linking directly to the issue

### Notes

- This workflow does **not** block merges and is **not** a required status check
- If the Teams webhook is unavailable, the job will fail but will not affect other workflows

---

## Workflow: Notify Teams on Pull Request Activity

**File:** `.github/workflows/notify-teams-on-pr.yml`

Sends a colour-coded Teams notification on pull request state changes.

### Trigger

```yaml
on:
  pull_request:
    types: [opened, closed, reopened, review_requested]
```

### Card Colours by Event

| Event | Card Colour | Meaning |
|---|---|---|
| PR opened | 🔵 Accent | New PR ready for review |
| PR merged | 🟢 Good | Successfully merged |
| PR closed (unmerged) | 🔴 Attention | Closed without merging |
| PR reopened | 🟡 Warning | Previously closed PR reopened |
| Review requested | 🔵 Accent | Reviewer has been assigned |

### Teams Card

Each notification includes:
- PR number and title
- Status (merged / closed / reopened / etc.)
- Author
- Branch direction (`feature/x → main`)
- Reviewer (when applicable)
- **"View Pull Request"** button

### Notes

- This workflow does **not** block merges and is **not** a required status check

---

## Workflow: Validate Docker Compose

**File:** `.github/workflows/validate-docker-compose.yml`

Validates any `docker-compose` file changes on a pull request through linting and a live smoke test. Failures block merge.

### Trigger

```yaml
on:
  pull_request:
    paths:
      - "**/docker-compose*.yml"
      - "**/docker-compose*.yaml"
      - "**/.env*"
```

### Jobs

#### Job 1 — Lint Docker Compose *(blocks merge on failure)*

| Check | Tool | Failure behaviour |
|---|---|---|
| Compose file detection | bash | Fails if no compose file found |
| Syntax validation | `docker compose config` | Blocks merge |
| YAML structure | `yamllint` | Blocks merge |
| Missing `restart:` policy | Python/yaml | Warning only |
| Unbound port exposure | Python/yaml | Warning only |
| `:latest` image tags | grep | Warning only |

On failure, sends a 🔴 **red Adaptive Card** to Teams with PR details and a link to the workflow run.

#### Job 2 — Smoke Test Docker Compose *(blocks merge on failure)*

1. Runs `docker compose up -d`
2. Waits **30 seconds**
3. Inspects every container via `docker inspect` for:
   - Non-running state → **fails, blocks merge**
   - `RestartCount > 0` → **fails, blocks merge**
4. Scans all logs for critical patterns:
   ```
   CRITICAL | FATAL | OOM | segfault | panic | killed
   ```
5. Tears down all containers with `--volumes --remove-orphans`

On container failure, sends a 🔴 **red Adaptive Card** to Teams.

#### Job 3 — Report Critical Log Errors *(warning only, merge allowed)*

Runs only when critical log patterns are detected in Job 2.

- Posts a **detailed comment on the PR** with the matching log lines
- Sends a 🟡 **yellow warning Adaptive Card** to Teams

On warning, sends a 🟡 **yellow Adaptive Card** to Teams with a link to the PR comment.

### Behaviour Summary

| Scenario | Merge | Teams |
|---|---|---|
| Lint passes, smoke test passes, no critical logs | ✅ Allowed | No notification |
| Lint fails | ❌ Blocked | 🔴 Red card |
| Container fails or restarts | ❌ Blocked | 🔴 Red card |
| Critical log entries found | ✅ Allowed (with warning) | 🟡 Yellow card + PR comment |

---

## Branch Protection Setup

To enforce these workflows as merge gates, configure branch protection on `main`:

**Settings → Branches → Edit rule for `main`**

Enable the following:

```
✅ Require a pull request before merging
   ✅ Require approvals: 1
   ✅ Dismiss stale reviews when new commits are pushed

✅ Require status checks to pass before merging
   ✅ Require branches to be up to date before merging
   → Lint Docker Compose            ← add as required check
   → Smoke Test Docker Compose      ← add as required check

✅ Block direct pushes
✅ Restrict deletions
```

> **Note:** Status checks only appear in the search box after the workflow has run at least once. Push the workflow files, open a test PR, let the jobs run, then return here to add the checks.

### Linking Issues to PRs (recommended)

To enforce that every PR references an issue, add a `.github/pull_request_template.md`:

```markdown
## Linked Issue
Closes #

## Description


## Checklist
- [ ] Linked to an issue
- [ ] Docker Compose validation passes
```

Or enforce it as a hard check by adding a `Check Linked Issue` job to any workflow that validates `Closes #<number>` in the PR body, and add it as a required status check.

---

## Secrets Reference

| Secret name | Where to get it | Used by |
|---|---|---|
| `MS_TEAMS_WEBHOOK_URI` | Teams channel → Webhook Bot → Create | All three workflows |

Add secrets at: **Settings → Secrets and variables → Actions → New repository secret**

---

## File Structure

```
.github/
├── workflows/
│   ├── notify-teams-on-issue.yml       # Teams alert on new issue
│   ├── notify-teams-on-pr.yml          # Teams alert on PR activity
│   └── validate-docker-compose.yml     # Lint + smoke test compose files
└── pull_request_template.md            # Optional: enforce linked issues
```

---

## Dependencies

| Tool / Service | Purpose | Version |
|---|---|---|
| [Webhook Bot](https://www.c-toss.com/webhook-bot/) | Teams notification relay | Latest |
| `actions/checkout` | Checkout code | `v4` |
| `actions/github-script` | Post PR comments | `v7` |
| `docker compose` | Syntax check + smoke test | Bundled on `ubuntu-latest` |
| `yamllint` | YAML linting | Installed via pip at runtime |
| Python 3 | Compose policy checks | Bundled on `ubuntu-latest` |# GITTemplate