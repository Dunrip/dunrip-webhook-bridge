# Webhook-to-Telegram Bridge

A production-ready FastAPI service that forwards GitHub and generic JSON webhooks to Telegram with resilience features.

## Features

- **Security**: HMAC-SHA256 signature verification, bearer token auth, body size limits
- **Resilience**: Circuit breaker, retry with backoff, idempotency (duplicate detection)
- **Observability**: Prometheus metrics, structured logging, deep health checks
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
- **OPEN**: After 5 consecutive failures, fast-fail with 502
- **HALF_OPEN**: After 60 seconds, allows one test request

Returns `502 Circuit breaker is OPEN` when tripped.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | *required* | Target chat/channel ID |
| `GITHUB_WEBHOOK_SECRET` | *required* | Secret for GitHub HMAC |
| `GENERIC_WEBHOOK_TOKEN` | *required* | Bearer token for generic webhooks |
| `LOG_LEVEL` | INFO | Logging verbosity |
| `MAX_BODY_SIZE` | 1048576 | Max payload size (bytes) |
| `TELEGRAM_RETRIES` | 2 | Retry attempts for Telegram API |
| `IDEMPOTENCY_TTL` | 3600 | Duplicate detection window (seconds) |
| `CIRCUIT_BREAKER_THRESHOLD` | 5 | Failures before opening circuit |
| `CIRCUIT_BREAKER_TIMEOUT` | 60 | Seconds before half-open |

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

42 tests covering all endpoints, auth, formatters, retry logic, circuit breaker, and idempotency.

## Architecture

```
GitHub Webhook → HMAC Verify → Idempotency Check → Format → Circuit Breaker → Telegram API
                                                     ↓
Generic Webhook → Token Verify ────────────────────→┘
                                                     ↓
                                               Prometheus Metrics
```
