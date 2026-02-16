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
- `ADMIN_API_KEYS` (preferred, scoped) **or** legacy `ADMIN_API_KEY`
- `GENERIC_WEBHOOK_TOKEN` (required by current app config; keep a random value if generic route is unused)

### GitHub webhook values (exact)
- **Payload URL**: `https://<your-domain>/webhook/github`
- **Content type**: `application/json`
- **Secret**: value of `GITHUB_WEBHOOK_SECRET`
- **Events**: Pushes, Pull requests, Issues, Releases, Workflow runs

Tip: `make wizard` prints these values again after setup.

---

## Required environment variables (what they are + how to get them)

Use this as a quick reference when filling `.env`.

- `TELEGRAM_BOT_TOKEN`
  - What it is: your Telegram bot API token.
  - How to get it: create a bot with [@BotFather](https://t.me/BotFather), then copy the token.

- `TELEGRAM_CHAT_ID`
  - What it is: target chat/group/channel ID where notifications are sent.
  - How to get it:
    1. Send a message to your bot.
    2. Open `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates`
    3. Read `chat.id` from response.

- `GITHUB_WEBHOOK_SECRET`
  - What it is: shared secret for GitHub webhook signature verification.
  - How to get it: generate your own random secret (example below), then paste the same value in both `.env` and GitHub Webhook "Secret" field.

- `GENERIC_WEBHOOK_TOKEN`
  - What it is: token for `POST /webhook/generic` (custom/non-GitHub senders).
  - How to get it: generate your own random secret. Keep it random even if you don’t use generic webhooks yet.

- Admin auth (choose one approach)
  - Preferred (scoped):
    - `ADMIN_API_KEYS` (or rotation pair `ADMIN_API_KEYS_ACTIVE` / `ADMIN_API_KEYS_PREVIOUS`)
    - Format: `key1:read,key2:replay,key3:admin`
  - Legacy (simple):
    - `ADMIN_API_KEY`
  - Purpose: protects admin/replay endpoints and `/stream/logs`.

Generate a strong secret quickly:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

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
   - `ADMIN_API_KEYS` (preferred) or `ADMIN_API_KEY` (legacy)
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
  - Cause: missing/invalid key, expired previous key, or wrong scope.
  - Fix: send `X-API-Key` (or `Authorization: Bearer ...`) using a key from `ADMIN_API_KEYS`/`ADMIN_API_KEYS_ACTIVE` with required scope.

- **Admin endpoint returns 403**
  - Cause: key scope is insufficient for endpoint.
  - Fix: use a `replay`/`admin` scoped key for replay endpoints, and `admin` key for `/stream/logs`.

- **Admin endpoint returns 503**
  - Cause: no admin key configuration found.
  - Fix: set `ADMIN_API_KEYS` (preferred) or legacy `ADMIN_API_KEY` and restart.

- **Confusing admin auth when both legacy/scoped keys exist**
  - Cause: `ADMIN_API_KEYS`, `ADMIN_API_KEYS_ACTIVE`, and `ADMIN_API_KEYS_PREVIOUS` take precedence over `ADMIN_API_KEY`.
  - Fix: prefer scoped keys; remove stale `ADMIN_API_KEY` to avoid confusion.

- **Startup crash or validation error from numeric env vars**
  - Cause: numeric keys set to empty strings (for example `ADMIN_KEY_ROTATION_GRACE_SECONDS=`).
  - Fix: remove empty numeric lines or set explicit values. Empty values now fall back to defaults, but explicit values are safer.

- **Smoke test fails to load env from another cwd**
  - Cause: running `scripts/smoke-test.sh` outside project root.
  - Fix: script now resolves `.env` from project root automatically. Override with `ENV_FILE=/path/to/.env` if needed.

- **Need quick setup diagnostics**
  - Run: `make doctor`
  - It validates `.env`, key precedence, numeric pitfalls, and compose env mapping.

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
