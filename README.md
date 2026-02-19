# Dunrip Webhook Bridge

[![CI](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/Dunrip/dunrip-webhook-bridge/branch/main/graph/badge.svg)](https://codecov.io/gh/Dunrip/dunrip-webhook-bridge)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker Hygiene](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/docker-hygiene.yml/badge.svg)](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/docker-hygiene.yml)
[![Dependency Scan](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/security-deps.yml/badge.svg)](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/security-deps.yml)
[![Secrets Scan](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/security-secrets.yml/badge.svg)](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/security-secrets.yml)
[![Latest Release](https://img.shields.io/github/v/release/Dunrip/dunrip-webhook-bridge?display_name=tag)](https://github.com/Dunrip/dunrip-webhook-bridge/releases/latest)

> **Quickstart (3 commands)**
>
> ```bash
> git clone https://github.com/Dunrip/dunrip-webhook-bridge.git
> cd dunrip-webhook-bridge
> make first-run
> ```

Production-ready FastAPI service that receives GitHub (and generic) webhooks and forwards formatted notifications to Telegram-first destinations (Discord/Slack adapters are in progress).

## Quick Navigation

- **First run (operator path):** [Quick Start](#quick-start)
- **Choose deploy mode:** [Deployment](#deployment)
- **Fast incident triage:** [Operator Troubleshooting Decision Tree](docs/ops/troubleshooting-decision-tree.md)
- **Release governance:** [Release Checklist](docs/release-checklist.md) + [Weekly KPI Scorecard](docs/ops/kpi-scorecard-template.md)

> **Code layout note:** Canonical runtime modules live under `app/` (for example `app/main.py`).

---

## Sample Telegram Output

### Before

```text
*Push* to `dunrip/webhook-bridge` by *octocat*
Branch: `main`
  `a1b2c3d` fix lint
[View diff](https://github.com/...)
```

### After (`MESSAGE_VERBOSITY=compact`, default)

```text
🚀 *Push* • `dunrip/webhook-bridge`
By: @octocat
Branch: main
Commits: 3
🔗 [View diff](https://github.com/...)
```

### After (`MESSAGE_VERBOSITY=detailed`)

```text
🚀 *Push* • `dunrip/webhook-bridge`
By: @octocat
Branch: main
Commits: 3
• a1b2c3d fix lint
🔗 [View diff](https://github.com/...)
```

## Deployment

Deploy in one click:

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/Dunrip/dunrip-webhook-bridge)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Dunrip/dunrip-webhook-bridge)

Then follow the full setup guides:
- Vercel: [`docs/deploy-vercel.md`](docs/deploy-vercel.md)
- Render: [`docs/deploy-render.md`](docs/deploy-render.md)

---

## What this project does

- Receives GitHub webhook events (push, pull request, issues, release, workflow run, etc.)
- Verifies signatures and prevents duplicate delivery abuse
- Sends formatted notifications to Telegram
- Supports replay of failed deliveries
- Exposes health and metrics endpoints for operations

### Channel Support Status

- ✅ **Telegram:** fully supported and production-ready
- 🚧 **Discord:** adapter scaffold present; full production wiring in progress
- 🚧 **Slack:** adapter scaffold present; full production wiring in progress

---

## Core Features

- **Security:** signature verification, admin API key auth, scoped key support, IP allowlists
- **Reliability:** retries, circuit breaker, idempotency, replay safeguards, dead-letter handling
- **Operations:** `/health`, `/health/deep`, `/metrics`, structured logs, request IDs
- **Setup UX:** setup wizard, smoke test, doctor diagnostics, Docker-first workflow

---

## Reliability Guarantees

- **Bounded outbound HTTP timeout:** all outbound HTTP calls use `HTTP_TIMEOUT_SECONDS` (default `10`, validated range `1.0..60.0`). This applies to the shared app client and destination webhook clients.
- **Storage backend behavior:**
  - `STORAGE_BACKEND=memory`: in-process volatile state (best for local/dev).
  - `STORAGE_BACKEND=redis`: Redis is primary. If Redis is unavailable at startup or runtime, the service falls back to memory and emits explicit warning/error logs (no silent fallback).
- **Operational visibility:** `/health/deep` includes storage backend status (`configured_backend`, `effective_backend`, `fallback_active`, `fallback_reason`) so operators can detect degraded persistence quickly.
- **Expectation in production:** use Redis-backed storage/rate limiting for durable idempotency and replay metadata across restarts/replicas. Memory fallback is best-effort continuity, not durable persistence.

---

## Quick Start

### 1) Clone and enter project

```bash
git clone https://github.com/Dunrip/dunrip-webhook-bridge.git
cd dunrip-webhook-bridge
```

### 2) Choose deploy mode before first run

- **Docker/self-hosted ops:** continue below with `make first-run`
- **Vercel/serverless:** use [`docs/deploy-vercel.md`](docs/deploy-vercel.md)
- **Render managed container:** use [`docs/deploy-render.md`](docs/deploy-render.md)

### 3) Run first-run sequence (Docker path)

```bash
make wizard
make up
make smoke
```

Equivalent shortcut: `make first-run`.

### 4) Add GitHub webhook

In your GitHub repository:
- **Settings → Webhooks → Add webhook**
- **Payload URL:** `https://<your-domain>/webhook/github`
- **Content type:** `application/json`
- **Secret:** same value as `GITHUB_WEBHOOK_SECRET` in your `.env`
- **Events:** Pushes, Pull requests, Issues, Releases, Workflow runs

---

## Required Environment Variables

You can configure these via `make wizard`.

- `TELEGRAM_BOT_TOKEN` — bot token from [@BotFather](https://t.me/BotFather)
- `TELEGRAM_CHAT_ID` — target chat/group/channel ID
- `GITHUB_WEBHOOK_SECRET` — shared secret for GitHub signature verification
- `GENERIC_WEBHOOK_TOKEN` — token for `/webhook/generic`
- `MESSAGE_VERBOSITY` — message detail level: `compact` (default) or `detailed`
- Admin auth (choose one):
  - Preferred: `ADMIN_API_KEYS` (supports either scoped CSV like `key1:read,key2:replay,key3:admin` or a single bare key like `my-admin-key`)
  - Legacy: `ADMIN_API_KEY` (equivalent to one bare admin key)

Generate secure secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Development Environment (uv-first)

```bash
uv sync --extra dev
uv run pytest
```

`pyproject.toml` + `uv.lock` are the canonical dependency sources. `requirements.txt` is kept for compatibility and is generated from the lockfile.

## Common Commands

```bash
make setup        # bootstrap and validate .env
make wizard       # interactive env setup
make up           # start services (docker compose)
make smoke        # run end-to-end smoke checks
make test-github  # send signed GitHub test payload
make doctor       # diagnose configuration/runtime issues
make benchmark    # local reliability benchmark (latency/error-rate)
make benchmark-baseline BASELINE=.benchmarks/local-baseline.json
make benchmark-compare BASELINE=.benchmarks/local-baseline.json
make down         # stop services
```

---

## API Reference (Compact)

| Endpoint | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `/webhook/github` | POST | GitHub HMAC signature | Receive GitHub webhook events |
| `/webhook/generic` | POST | `X-Webhook-Token` | Receive generic webhook payloads |
| `/health` | GET | None | Basic liveness check |
| `/health/deep` | GET | None | Downstream-aware health (Telegram + breaker + storage backend state) |
| `/metrics` | GET | None | Prometheus metrics export |
| `/deliveries` | GET | Admin API key (`read+`) | List failed deliveries |
| `/deliveries/{id}/replay` | POST | Admin API key (`replay+`) | Replay one failed delivery |
| `/deliveries/replay-all` | POST | Admin API key (`replay+`) | Replay eligible failed deliveries |
| `/stream/logs` | WS | Admin API key (`read+`) | Stream operational events/log metadata |


---

## Routing Use Cases

- [Multiple repositories → one chat](docs/use-cases-routing.md#multiple-repositories--one-chat)
- [Multi-chat routing](docs/use-cases-routing.md#multi-chat-routing)

---


## Deployment Modes

- **Fastest setup:** Vercel (free tier friendly) — see [`docs/deploy-vercel.md`](docs/deploy-vercel.md)
  - For production reliability on serverless, use Redis-backed state (`STORAGE_BACKEND=redis`, `RATE_LIMIT_BACKEND=redis`).
- Render deployment is supported via `deploy/render.yaml` — see [`docs/deploy-render.md`](docs/deploy-render.md)
- **Best long-running ops:** Docker + reverse proxy with HTTPS on VPS/self-hosted

Deployment artifacts are organized under [`deploy/`](deploy/) (`Dockerfile`, `docker-compose.yml`, `render.yaml`, `prometheus.yml`, canonical `vercel.json`). A root `vercel.json` is kept for Vercel auto-detection.

---

## Security Notes

- Do not commit `.env` or secrets
- Use strong random secrets for all token/key fields
- Prefer scoped admin keys over legacy single key
- Keep CI security workflows enabled (dependency + secrets scanning)
- Follow the CI failure triage checklist: [`docs/ops/ci-failure-triage.md`](docs/ops/ci-failure-triage.md)
- Use benchmark baseline guardrails: [`docs/monitoring/reliability-benchmark.md`](docs/monitoring/reliability-benchmark.md)

---

## Troubleshooting

Start here for fastest triage: [docs/ops/troubleshooting-decision-tree.md](docs/ops/troubleshooting-decision-tree.md)

- `make smoke` fails with 401 on admin endpoints:
  - check admin key precedence (`ADMIN_API_KEYS*` overrides `ADMIN_API_KEY`)
- Service fails on startup with env validation errors:
  - run `make doctor`
  - check for empty numeric env values
- GitHub webhook 401 invalid signature:
  - webhook secret in GitHub must exactly match `GITHUB_WEBHOOK_SECRET`

### Copy/paste recovery playbook (env mismatch after edits)

```bash
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml --env-file .env up -d --force-recreate
make doctor
make smoke
```

### `make doctor` quick fixes

- Doctor says **`.env not found`**
  - Fix: `cp .env.example .env && make wizard`
- Doctor warns **scoped keys override legacy key**
  - Fix: keep one mode only (preferred scoped keys, or remove `ADMIN_API_KEYS*` to use legacy `ADMIN_API_KEY`)
- Doctor says **docker compose mapping missing ADMIN_API_KEY**
  - Fix: add `- ADMIN_API_KEY=${ADMIN_API_KEY}` under `webhook-bridge.environment` in `deploy/docker-compose.yml`
- Doctor reports **container key mismatch**
  - Fix: `docker compose -f deploy/docker-compose.yml down && docker compose -f deploy/docker-compose.yml --env-file .env up -d --force-recreate`

---

## License

MIT — see `LICENSE`.
