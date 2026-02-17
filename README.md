# Dunrip Webhook Bridge

[![CI](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Dunrip/dunrip-webhook-bridge/actions/workflows/ci.yml)
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

Production-ready FastAPI service that receives GitHub (and generic) webhooks and forwards formatted notifications to Telegram.

---

## Sample Telegram Output

```text
🚀 push in dunrip/webhook-bridge
branch: main
commits: 3
by: @octocat
```

> Note: Replace with real screenshot/output assets when available.

---

## What this project does

- Receives GitHub webhook events (push, pull request, issues, release, workflow run, etc.)
- Verifies signatures and prevents duplicate delivery abuse
- Sends formatted notifications to Telegram
- Supports replay of failed deliveries
- Exposes health and metrics endpoints for operations

---

## Core Features

- **Security:** signature verification, admin API key auth, scoped key support, IP allowlists
- **Reliability:** retries, circuit breaker, idempotency, replay safeguards, dead-letter handling
- **Operations:** `/health`, `/health/deep`, `/metrics`, structured logs, request IDs
- **Setup UX:** setup wizard, smoke test, doctor diagnostics, Docker-first workflow

---

## Quick Start

### 1) Clone and enter project

```bash
git clone https://github.com/Dunrip/dunrip-webhook-bridge.git
cd dunrip-webhook-bridge
```

### 2) Run guided setup

```bash
make first-run
```

This runs wizard + startup + smoke checks.

### 3) Add GitHub webhook

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
- Admin auth (choose one):
  - Preferred: `ADMIN_API_KEYS` (scoped format like `key1:read,key2:replay,key3:admin`)
  - Legacy: `ADMIN_API_KEY`

Generate secure secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Common Commands

```bash
make setup        # bootstrap and validate .env
make wizard       # interactive env setup
make up           # start services (docker compose)
make smoke        # run end-to-end smoke checks
make test-github  # send signed GitHub test payload
make doctor       # diagnose configuration/runtime issues
make down         # stop services
```

---

## API Reference (Compact)

| Endpoint | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `/webhook/github` | POST | GitHub HMAC signature | Receive GitHub webhook events |
| `/webhook/generic` | POST | `X-Webhook-Token` | Receive generic webhook payloads |
| `/health` | GET | None | Basic liveness check |
| `/health/deep` | GET | None | Downstream-aware health (Telegram + breaker state) |
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

## Deployment

- **Recommended:** Docker + reverse proxy with HTTPS
- Render deployment is supported via `render.yaml`
- For self-hosted VPS, use your domain and forward to service on port `8000`

---

## Security Notes

- Do not commit `.env` or secrets
- Use strong random secrets for all token/key fields
- Prefer scoped admin keys over legacy single key
- Keep CI security workflows enabled (dependency + secrets scanning)

---

## Troubleshooting

- `make smoke` fails with 401 on admin endpoints:
  - check admin key precedence (`ADMIN_API_KEYS*` overrides `ADMIN_API_KEY`)
- Service fails on startup with env validation errors:
  - run `make doctor`
  - check for empty numeric env values
- GitHub webhook 401 invalid signature:
  - webhook secret in GitHub must exactly match `GITHUB_WEBHOOK_SECRET`

### `make doctor` quick fixes

- Doctor says **`.env not found`**
  - Fix: `cp .env.example .env && make wizard`
- Doctor warns **scoped keys override legacy key**
  - Fix: keep one mode only (preferred scoped keys, or remove `ADMIN_API_KEYS*` to use legacy `ADMIN_API_KEY`)
- Doctor says **docker compose mapping missing ADMIN_API_KEY**
  - Fix: add `- ADMIN_API_KEY=${ADMIN_API_KEY}` under `webhook-bridge.environment` in `docker-compose.yml`
- Doctor reports **container key mismatch**
  - Fix: `docker compose down && docker compose --env-file .env up -d --force-recreate`

---

## License

MIT — see `LICENSE`.
