# Monitoring Alerts (Starter)

Baseline alert recommendations for Dunrip Webhook Bridge.

## Service Availability

### `WebhookBridgeDown`
- **Expr:** `up{job="webhook-bridge"} == 0`
- **For:** `2m`
- **Severity:** critical
- **Action:** check container/process status and reverse proxy health.

### `WebhookBridgeDeepHealthDegraded`
- **Expr:** `probe_success{job="webhook-bridge-deep-health"} == 0`
- **For:** `5m`
- **Severity:** warning
- **Action:** Telegram API reachability/token validity checks.

## Error Rate & Reliability

### `WebhookErrorRateHigh`
- **Expr:**
  ```promql
  sum(rate(webhook_requests_total{status=~"auth_error|delivery_failed|malformed_json|invalid_payload"}[5m]))
  /
  clamp_min(sum(rate(webhook_requests_total[5m])), 0.001) > 0.05
  ```
- **For:** `10m`
- **Severity:** critical
- **Action:** inspect request logs, signature/token failures, upstream payload quality.

### `TelegramDeliveryFailures`
- **Expr:** `sum(rate(telegram_messages_total{status="failed"}[5m])) > 0`
- **For:** `10m`
- **Severity:** warning
- **Action:** verify Telegram token/chat_id, outbound network, circuit breaker state.

## Throughput & Latency

### `WebhookP95LatencyHigh`
- **Expr:**
  ```promql
  histogram_quantile(0.95, sum(rate(webhook_request_duration_seconds_bucket[5m])) by (le)) > 2
  ```
- **For:** `10m`
- **Severity:** warning
- **Action:** check downstream latency (Telegram, Redis), host resource pressure.

### `WebhookEnqueueP95High`
- **Expr:**
  ```promql
  histogram_quantile(0.95, sum(rate(webhook_enqueue_duration_seconds_bucket[5m])) by (le, source)) > 0.25
  ```
- **For:** `10m`
- **Severity:** warning
- **Action:** validate ingest path speed, Redis/network latency, signature verification overhead.

### `WebhookProcessingP95High`
- **Expr:**
  ```promql
  histogram_quantile(0.95, sum(rate(webhook_processing_duration_seconds_bucket[5m])) by (le, source, event_type)) > 3
  ```
- **For:** `10m`
- **Severity:** warning
- **Action:** inspect destination slowness and worker throughput.

## Retry / DLQ Signals

### `WebhookRetrySpike`
- **Expr:** `sum(rate(webhook_retries_total[5m])) > 1`
- **For:** `10m`
- **Severity:** warning
- **Action:** inspect retry classifications and upstream/downstream health.

### `WebhookDLQGrowth`
- **Expr:** `sum(increase(webhook_dlq_growth_total[15m])) > 0`
- **For:** `15m`
- **Severity:** warning
- **Action:** triage failure reasons, execute targeted replay, and inspect circuit breaker behavior.

## Operational Notes

- Route critical alerts to on-call (PagerDuty/Telegram).
- Keep warning alerts in chat channels for triage.
- Pair alerts with runbooks in `docs/runbooks/`.
- Revisit thresholds after 1-2 weeks of baseline traffic.
