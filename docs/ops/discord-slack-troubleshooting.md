# Discord/Slack Delivery Troubleshooting Runbook

Use this runbook when Discord/Slack routes fail, flap, or silently skip.

## 1) Quick triage

```bash
BASE_URL=${BASE_URL:-http://127.0.0.1:8000}
curl -sS "$BASE_URL/health/deep" | python3 -m json.tool
```

Check:
- `destinations.registered`
- `destinations.active`
- `destinations.readiness.<destination>.reason`

Common readiness reasons:
- `disabled_by_feature_flag` → destination turned off via `DESTINATION_FEATURE_FLAGS`
- `missing_webhook_url` → webhook URL env var missing
- `missing_telegram_config` → Telegram fallback not configured

## 2) Validate config correctness

### Discord
- `DISCORD_WEBHOOK_URL` must be: `https://.../api/webhooks/...`

### Slack
- `SLACK_WEBHOOK_URL` must be: `https://hooks.slack.com/services/...`

### Strict mode for safer startup
- Set `ROUTES_STRICT_VALIDATION=true` to fail startup if routes reference unready destinations.
- Keep `false` in migration mode if you want warning-only behavior.

## 3) Inspect retries and rate limiting

Prometheus metrics to inspect:
- `destination_delivery_attempts_total`
- `destination_delivery_failures_total{classification=...}`
- `destination_delivery_retries_total{classification=...}`
- `destination_rate_limit_events_total`
- `destination_delivery_duration_seconds`

Interpretation:
- Spike in `classification="rate_limit"` → destination throttling; lower burst, add jitter, or reduce fanout.
- Spike in `classification="payload_invalid"` → malformed payload/format assumptions.
- Spike in `classification="server"` or `"network"` → remote outage or transient transport failures.

## 4) Failure mode mapping

- **HTTP 400/401/403/404**
  - Usually non-retryable config/payload problems.
  - Rotate/regenerate webhook URL and verify route filters.

- **HTTP 429**
  - Retry with `Retry-After` is automatic.
  - Tune:
    - `DESTINATION_MAX_RETRIES`
    - `DESTINATION_RETRY_BASE_SECONDS`
    - `DESTINATION_RETRY_MAX_SECONDS`

- **HTTP 5xx / network errors**
  - Automatically retried within configured bounds.
  - Escalate if sustained beyond provider incident window.

## 5) Security callouts

### IP allowlists / egress controls
- If running behind strict firewalls, ensure egress to:
  - Discord webhook domains (`discord.com`)
  - Slack webhook domains (`hooks.slack.com`)
- Keep allowlists narrow and review quarterly.

### Webhook secret hygiene
- Treat webhook URLs as secrets (they are bearer credentials).
- Never commit URLs to repo or logs.
- Rotate immediately if leaked.
- Prefer env-injected secrets from your deploy platform.

### Redis durability
- For production replay/recovery reliability, prefer Redis backend over in-memory fallback.
- Monitor deep health storage block (`storage.fallback_active`).
- If fallback is active unexpectedly, treat as degraded durability and restore Redis.

## 6) Recovery checklist

1. Confirm `/health/deep` readiness state for destinations.
2. Fix env/config and redeploy.
3. Validate metrics stabilize (retries/failures decline).
4. Replay failed deliveries if needed (`/deliveries/replay` endpoints).
5. Capture post-incident notes in `docs/release-evidence/` or incident tracker.
