# High Error Rate Runbook

## Trigger
- 5xx or 4xx errors significantly above baseline
- Alert from metrics/log monitoring

## Triage Checklist
1. Identify dominant error codes (`AUTH_*`, `VALIDATION_ERROR`, `RATE_LIMIT_EXCEEDED`, `STORAGE_ERROR`, `CIRCUIT_BREAKER_OPEN`).
2. Correlate by `request_id` and endpoint (`/webhook/github`, `/webhook/generic`, `/deliveries/*`).
3. Check deployment/config changes and external dependency health.

## Common Root Causes
- Invalid webhook signatures/tokens after secret rotation.
- Upstream payload shape changes causing validation failures.
- Telegram/API dependency degradation.
- Redis/storage connectivity issues.
- Aggressive client retries hitting rate limiter.

## Mitigation
- Roll back recent config/code changes if suspicious.
- Increase logging sample for failed requests.
- Temporarily tighten/relax limits based on abuse vs legitimate load.
- Use replay endpoints after issue resolution.

## Verification
- Error rate back to baseline.
- Successful webhook deliveries sustained.
- No new alerts for at least one alert window.
