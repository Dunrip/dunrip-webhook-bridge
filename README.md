# Webhook-to-Telegram Bridge

A production-ready FastAPI service that forwards GitHub and generic JSON webhooks to Telegram with resilience features.

## Features

- **Security**: HMAC-SHA256 signature verification, bearer token auth, admin API key protection, trusted proxy handling, body size limits
- **Resilience**: Circuit breaker, retry with backoff, idempotency (duplicate detection)
- **Observability**: Prometheus metrics, structured logging, deep health checks, WebSocket event stream
- **Extensibility**: Unified formatter registry (`formatters.py`), optional routing, template support
- **Docker**: Multi-stage build, docker-compose with optional monitoring stack

## Supported Events

| Event | Description |
|-------|-------------|
| `push` | Git commits with diff links |
| `pull_request` | Open/close/update with PR links |
| `issues` | Open/close/update with issue links |
| `release` | Published/draft/prerelease with badges |
| `workflow_run` | CI/CD status with emojis (✅❌🚫⏭️) |
| `generic` | Custom webhooks with title/body/url |

## Quick Start (Local)

1. **Create a Telegram bot** via [@BotFather](https://t.me/BotFather) and get the token.

2. **Get your chat ID** by sending a message to the bot, then visiting:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

4. **Run locally**:
   ```bash
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

## Docker Deployment

```bash
# Build and run
docker-compose up -d

# With monitoring stack (Prometheus + Grafana)
docker-compose --profile monitoring up -d
```

### Production Docker Compose

```yaml
version: '3.8'
services:
  webhook-bridge:
    build: .
    ports:
      - "8000:8000"
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - GITHUB_WEBHOOK_SECRET=${GITHUB_WEBHOOK_SECRET}
      - GENERIC_WEBHOOK_TOKEN=${GENERIC_WEBHOOK_TOKEN}
      - ADMIN_API_KEY=${ADMIN_API_KEY}
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
```

## GitHub Webhook Setup

1. Go to your repo **Settings > Webhooks > Add webhook**
2. Set Payload URL to `https://your-domain/webhook/github`
3. Set Content type to `application/json`
4. Set Secret to your `GITHUB_WEBHOOK_SECRET` value
5. Select events: Pushes, Pull requests, Issues, Releases, Workflow runs

## Generic Webhook

```bash
curl -X POST https://your-domain/webhook/generic \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: your-generic-token" \
  -d '{"title": "Deploy", "body": "v1.2.3 deployed", "url": "https://example.com"}'
```

## Admin API Protection

Replay/admin endpoints and the WebSocket stream require `ADMIN_API_KEY`.

Protected endpoints:
- `GET /deliveries`
- `POST /deliveries/{id}/replay`
- `POST /deliveries/replay-all`
- `WS /stream/logs`

Accepted auth headers:
- `X-API-Key: <ADMIN_API_KEY>`
- `Authorization: Bearer <ADMIN_API_KEY>`

If `ADMIN_API_KEY` is missing, HTTP admin endpoints return `503` (misconfigured), and WebSocket auth fails.

## Security Notes

### Trusted Proxies and X-Forwarded-For (IP spoofing protection)

`TRUSTED_PROXIES` controls when `X-Forwarded-For` is trusted:

- **Empty `TRUSTED_PROXIES` (default):** ignore `X-Forwarded-For`; use direct client IP only.
- **Set `TRUSTED_PROXIES`:** trust `X-Forwarded-For` **only** when request source IP matches configured IP/CIDR.

Example:
```env
TRUSTED_PROXIES=10.0.0.10,10.0.0.0/24
```

This behavior is used by rate limiting to reduce spoofing risk.

## Health Checks

```bash
# Basic health
GET /health

# Deep health (verifies Telegram API connectivity)
GET /health/deep

# Prometheus metrics
GET /metrics
```

## Circuit Breaker

The service includes a circuit breaker to prevent hammering Telegram during outages:

- **CLOSED**: Normal operation (default)
- **OPEN**: After `CIRCUIT_BREAKER_THRESHOLD` consecutive failures, fast-fail with 502
- **HALF_OPEN**: After `CIRCUIT_BREAKER_TIMEOUT` seconds, allows **1 concurrent trial request**

Returns `502 Circuit breaker is OPEN` when tripped.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | *required* | Target chat/channel ID |
| `GITHUB_WEBHOOK_SECRET` | *required* | Secret for GitHub HMAC |
| `GENERIC_WEBHOOK_TOKEN` | *required* | Bearer token for generic webhooks |
| `ADMIN_API_KEY` | *required for admin/replay/stream* | API key for replay admin endpoints and `/stream/logs` |
| `LOG_LEVEL` | INFO | Logging verbosity |
| `MAX_BODY_SIZE` | 1048576 | Max payload size (bytes) |
| `IDEMPOTENCY_TTL` | 3600 | Duplicate detection window (seconds) |
| `FAILED_DELIVERY_TTL` | 604800 | Failed-delivery retention window (seconds) |
| `TELEGRAM_RETRIES` | 2 | Retry attempts for Telegram API |
| `CIRCUIT_BREAKER_THRESHOLD` | 5 | Failures before opening circuit |
| `CIRCUIT_BREAKER_TIMEOUT` | 60 | Seconds before half-open |
| `STORAGE_BACKEND` | memory | Storage backend (`memory` or `redis`) |
| `REDIS_URL` | redis://redis:6379/0 | Redis connection string |
| `REDIS_KEY_PREFIX` | webhook_bridge | Redis key namespace prefix |
| `RATE_LIMIT_BACKEND` | memory | Rate limit backend (`memory` or `redis`) |
| `RATE_LIMIT_IP_PER_MINUTE` | 10 | Per-IP requests per minute |
| `RATE_LIMIT_TOKEN_PER_MINUTE` | 30 | Per-token requests per minute (generic webhook) |
| `TRUSTED_PROXIES` | empty | Comma-separated trusted proxy IPs/CIDRs for XFF handling |
| `ROUTES_YAML` | empty | Routing config path or inline YAML |
| `DISCORD_WEBHOOK_URL` | empty | Discord destination webhook |
| `SLACK_WEBHOOK_URL` | empty | Slack destination webhook |
| `GITHUB_APP_ID` | empty | GitHub App ID (enables app endpoints) |
| `GITHUB_APP_PRIVATE_KEY` | empty | GitHub App private key |

## Monitoring

When running with `--profile monitoring`:

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)

Key metrics:
- `webhook_requests_total` — Webhook volume by source/event/status
- `webhook_request_duration_seconds` — Latency histogram
- `telegram_messages_total` — Delivery success/failure
- `circuit_breaker_state_changes_total` — Circuit transitions

## Testing

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Architecture

Shared clients (Redis + httpx) are initialized once via FastAPI lifespan and closed on shutdown.

```
Incoming Webhooks
   ├─ /webhook/github  ──> HMAC Verify
   └─ /webhook/generic ──> Token Verify
            │
            ├─> Rate Limit (client IP from TRUSTED_PROXIES/XFF policy)
            ├─> Idempotency + Failed Delivery Storage (Memory/Redis)
            ├─> Formatter Registry (formatters.py) / Templates
            ├─> Circuit Breaker (HALF_OPEN: 1 concurrent trial)
            ├─> Routing (Telegram / Discord / Slack)
            └─> Broadcast Event (WebSocket stream, ADMIN_API_KEY protected)

Lifespan-managed shared clients:
  - app.state.http  (httpx.AsyncClient)
  - app.state.redis (optional Redis client)
```
