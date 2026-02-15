# Redis Connection Failed Runbook

## Symptoms
- Warnings about Redis unavailable / fallback to memory
- Missing cross-instance idempotency and distributed rate limiting
- Increased duplicate processing risk in multi-instance setups

## Diagnosis
1. Check Redis endpoint reachability, DNS, TLS, and credentials.
2. Validate `REDIS_URL` and network policy/firewall.
3. Inspect Redis server health (CPU/memory/evictions/connections).

## Immediate Mitigation
- Service can run with memory fallback (single instance safest).
- If multi-instance, reduce risk by pinning traffic to one instance until Redis recovers.
- Increase monitoring for duplicate deliveries.

## Recovery Steps
1. Restore Redis connectivity.
2. Restart service (or force reconnection) to re-enable Redis backend.
3. Verify logs no longer show fallback warnings.
4. Validate idempotency/rate limit behavior end-to-end.

## Postmortem Data to Capture
- Outage start/end times
- Error counts by code/request_id
- Root cause and preventive actions
