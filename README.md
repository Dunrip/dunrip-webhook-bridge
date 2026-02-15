# Dunrip Webhook Bridge

Production-ready FastAPI service for forwarding GitHub and generic webhooks to Telegram.

## Quick Start (2 minutes)

### 1) Configure environment
```bash
make setup
# If setup reports missing values, run:
make wizard
```

### 2) Start with Docker
```bash
make up
```

### 3) Run smoke checks
```bash
make smoke
```

If all checks pass, your bridge is up.

---

## Minimal Mode (GitHub -> Telegram only)

Minimal mode is the fastest onboarding path: only GitHub events forwarded to Telegram.

Required `.env` values:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GITHUB_WEBHOOK_SECRET`
- `ADMIN_API_KEY`
- `GENERIC_WEBHOOK_TOKEN` (required by current app config; keep a random value if generic route is unused)

### GitHub webhook values (exact)
- **Payload URL**: `https://<your-domain>/webhook/github`
- **Content type**: `application/json`
- **Secret**: value of `GITHUB_WEBHOOK_SECRET`
- **Events**: Pushes, Pull requests, Issues, Releases, Workflow runs

Tip: `make wizard` prints these values again after setup.

---

## Render Deployment (recommended)

Use the included blueprint:

1. Push repo to GitHub.
2. In Render: **New + -> Blueprint**.
3. Select this repo (Render reads `render.yaml`).
4. Set required env vars in Render:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GITHUB_WEBHOOK_SECRET`
   - `GENERIC_WEBHOOK_TOKEN`
   - `ADMIN_API_KEY`
5. Deploy.
6. Confirm health check passes at `/health`.

Optional Redis is documented in `render.yaml` comments and `docs/deploy-render.md`.

---

## Post-deploy smoke checks

Run locally against your deployed URL:

```bash
BASE_URL="https://your-render-service.onrender.com" ./scripts/smoke-test.sh
```

Checks performed:
- `GET /health`
- `GET /health/deep`
- `GET /metrics`
- Signed GitHub `ping` webhook to `/webhook/github`
- Optional admin auth checks for `/deliveries`

---

## Common setup mistakes (and exact fixes)

- **`make setup` reports missing vars**
  - Fix: run `make wizard` and fill required values.

- **`/health/deep` returns 503**
  - Cause: Telegram token invalid or Telegram API unreachable.
  - Fix: verify `TELEGRAM_BOT_TOKEN`, then redeploy/restart.

- **GitHub webhook returns 401 invalid signature**
  - Cause: GitHub secret != `GITHUB_WEBHOOK_SECRET`.
  - Fix: set same secret in GitHub webhook settings and `.env`/Render.

- **Admin endpoint returns 401**
  - Cause: missing `X-API-Key` or wrong `ADMIN_API_KEY`.
  - Fix: send `X-API-Key: <ADMIN_API_KEY>`.

- **Admin endpoint returns 503**
  - Cause: `ADMIN_API_KEY` not configured.
  - Fix: set `ADMIN_API_KEY` and restart.

---

## Useful commands

```bash
make setup   # bootstrap .env and validate required vars
make wizard  # interactive env setup
make up      # docker compose up -d
make smoke   # smoke test running service
make down    # docker compose down
```

## Manual local run (without Docker)

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Hardening (v1.1)

- **Admin audit trail** for `/deliveries`, `/deliveries/{id}/replay`, `/deliveries/replay-all`, and `/stream/logs` WebSocket auth attempts.
- Structured audit fields include: `action`, `request_id`, `client_ip`, `auth_result`, `delivery_id`, `status`, `actor` (API key fingerprint; no secrets logged).
- **Endpoint-specific limits**:
  - `RATE_LIMIT_ADMIN_PER_MINUTE` (default `20`)
  - `WS_CONNECTS_PER_MINUTE` (default `10`)
  - `WS_MAX_CONNECTIONS_PER_IP` (default `3`)
- **DLQ + replay safeguards**:
  - Failed-delivery metadata: `replay_attempts`, `last_replay_at`, `last_replay_status`
  - Cooldown for repeated replay: `REPLAY_COOLDOWN_SECONDS` (default `30`)
  - Max replay attempts: `MAX_REPLAY_ATTEMPTS` (default `10`), then status moves to `dead_letter`
  - Replay operation idempotency via `Idempotency-Key` header

## Network Boundary Controls (v1.2 Track B)

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

Migration notes: see `docs/migration-v1.2.md`.

## Testing

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q
```
