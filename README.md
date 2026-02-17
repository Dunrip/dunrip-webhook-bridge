# Dunrip Webhook Bridge

Production-ready FastAPI service for forwarding GitHub and generic webhooks to Telegram.

## Beginner Quickstart (Dead Simple)

### 1) Install Docker
Install Docker Desktop (Mac/Windows) or Docker Engine + Compose plugin (Linux), then make sure Docker is running.

### 2) Run one command
```bash
make first-run
```

This runs, in order:
1. `make wizard` (interactive `.env` setup)
2. `make up` (start service)
3. `make smoke` (sanity checks)

### 3) Paste webhook settings in GitHub
Use these exact values in GitHub → Settings → Webhooks:

- **Payload URL**: `https://<your-domain>/webhook/github`
- **Content type**: `application/json`
- **Secret**: value of `GITHUB_WEBHOOK_SECRET` in your `.env`
- **Recommended events**: Pushes, Pull requests, Issues, Releases, Workflow runs

Tip: run `make test-github` to send a signed sample webhook and verify setup end-to-end.

---

## Copy-paste Payload URL templates

### VPS / self-hosted (public domain)
```text
https://your-domain.com/webhook/github
```

### Render
```text
https://your-service-name.onrender.com/webhook/github
```

### Local tunnel (ngrok / cloudflared)
```text
https://your-random-subdomain.ngrok-free.app/webhook/github
```

---

## Top 5 setup mistakes (and fixes)

1. **Docker installed but daemon not running**
   - Symptom: `make up` fails to connect to Docker.
   - Fix: start Docker Desktop/daemon, then retry.

2. **Missing or placeholder values in `.env`**
   - Symptom: startup or doctor errors for required vars.
   - Fix: run `make wizard` and fill real values.

3. **GitHub signature failures (401)**
   - Symptom: webhook deliveries fail with invalid signature.
   - Fix: GitHub webhook Secret must exactly match `GITHUB_WEBHOOK_SECRET`.

4. **Admin key confusion (scoped vs legacy)**
   - Symptom: auth behaves unexpectedly.
   - Fix: `ADMIN_API_KEYS*` takes precedence over `ADMIN_API_KEY`; remove stale legacy key.

5. **Service running but health checks fail**
   - Symptom: `make smoke` fails on `/health` or `/health/deep`.
   - Fix: verify `BASE_URL`, then inspect logs: `docker compose logs -f webhook-bridge`.

For a full diagnosis, run:
```bash
make doctor
```

---

## Minimal Mode (GitHub -> Telegram only)

Required `.env` values:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GITHUB_WEBHOOK_SECRET`
- `ADMIN_API_KEYS` (preferred, scoped) **or** legacy `ADMIN_API_KEY`
- `GENERIC_WEBHOOK_TOKEN` (required by current app config; keep a random value if generic route is unused)

---

## Required environment variables (what they are + how to get them)

- `TELEGRAM_BOT_TOKEN`
  - Telegram bot API token from [@BotFather](https://t.me/BotFather).
- `TELEGRAM_CHAT_ID`
  - Target chat/group/channel ID.
  - Retrieve from: `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates`
- `GITHUB_WEBHOOK_SECRET`
  - Shared secret for GitHub signature verification.
- `GENERIC_WEBHOOK_TOKEN`
  - Token for `POST /webhook/generic`.
- Admin auth (choose one):
  - Preferred scoped keys: `ADMIN_API_KEYS` (or `ADMIN_API_KEYS_ACTIVE` / `ADMIN_API_KEYS_PREVIOUS`)
  - Legacy key: `ADMIN_API_KEY`

Generate a strong secret quickly:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Render Deployment (recommended)

1. Push repo to GitHub.
2. In Render: **New + -> Blueprint**.
3. Select this repo (Render reads `render.yaml`).
4. Set required env vars in Render.
5. Deploy and confirm `/health`.

Optional Redis is documented in `render.yaml` comments and `docs/deploy-render.md`.

---

## Useful commands

```bash
make setup   # bootstrap .env and validate required vars
make wizard  # interactive env setup
make up      # docker compose up -d
make smoke   # smoke test running service
make doctor  # diagnose env/compose setup issues
make down    # docker compose down
```

## Manual local run (without Docker)

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Hardening

- **Scoped admin keys**:
  - `read` for read-only admin endpoints (`GET /deliveries`)
  - `replay` for replay endpoints (`POST /deliveries/{id}/replay`, `POST /deliveries/replay-all`) and read-only access
  - `admin` for full access (including `WS /stream/logs`)
- **Key rotation support**:
  - `ADMIN_API_KEYS_ACTIVE`, `ADMIN_API_KEYS_PREVIOUS`
  - `ADMIN_KEY_ROTATION_STARTED_AT`, `ADMIN_KEY_ROTATION_GRACE_SECONDS`
  - Previous keys are accepted only during grace window and emit warnings when used.
- **Admin audit trail** for `/deliveries`, `/deliveries/{id}/replay`, `/deliveries/replay-all`, and `/stream/logs` WebSocket auth attempts.
- Structured audit fields include: `action`, `request_id`, `client_ip`, `auth_result`, `delivery_id`, `status`, `actor_key_id`, and `reason` (no raw keys logged).
- **Endpoint-specific limits**:
  - `RATE_LIMIT_ADMIN_PER_MINUTE` (default `20`)
  - `WS_CONNECTS_PER_MINUTE` (default `10`)
  - `WS_MAX_CONNECTIONS_PER_IP` (default `3`)
- **DLQ + replay safeguards**:
  - Failed-delivery metadata: `replay_attempts`, `last_replay_at`, `last_replay_status`
  - Cooldown for repeated replay: `REPLAY_COOLDOWN_SECONDS` (default `30`)
  - Max replay attempts: `MAX_REPLAY_ATTEMPTS` (default `10`), then status moves to `dead_letter`
  - Replay operation idempotency via `Idempotency-Key` header

## Network Boundary Controls

Admin and streaming endpoints support optional CIDR/IP allowlists:

- `ADMIN_IP_ALLOWLIST`: enforced on all `/deliveries*` endpoints
- `WS_IP_ALLOWLIST`: enforced on `/stream/logs` websocket
  - If empty, websocket falls back to `ADMIN_IP_ALLOWLIST`

Behavior:

- Empty allowlist = disabled (no IP-based blocking)
- Configured allowlist = fail-closed (non-matching clients are denied)
- Client IP extraction is trusted-proxy-aware via `TRUSTED_PROXIES`
- Admin HTTP denial returns `403` structured JSON with `request_id`
- WebSocket denial closes with policy-violation code (`1008`)

Examples:

```env
TRUSTED_PROXIES=10.0.0.0/24
ADMIN_IP_ALLOWLIST=203.0.113.10,203.0.113.0/24
WS_IP_ALLOWLIST=198.51.100.0/24
```

```env
# Reuse admin allowlist for websocket by leaving WS_IP_ALLOWLIST empty
ADMIN_IP_ALLOWLIST=203.0.113.0/24
WS_IP_ALLOWLIST=
```

Migration notes: see `docs/migration-guide.md`.

## Security hygiene

- CI dependency scanning: [`.github/workflows/security-deps.yml`](.github/workflows/security-deps.yml) (uses `pip-audit`, fails on known vulnerabilities).
- CI secrets scanning: [`.github/workflows/security-secrets.yml`](.github/workflows/security-secrets.yml) (uses `gitleaks`, fails on findings).
- Gitleaks allowlist/baseline config: [`.gitleaks.toml`](.gitleaks.toml) (keep exceptions minimal and documented).
- Incident response runbook: [`docs/runbooks/security-incident.md`](docs/runbooks/security-incident.md).

## Testing

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q
```
