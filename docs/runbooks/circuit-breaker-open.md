# Circuit Breaker Open Runbook

## Symptoms
- API returns `CIRCUIT_BREAKER_OPEN`
- Telegram sends fail repeatedly
- Delivery failures increase in `/deliveries`

## Immediate Actions
1. Confirm Telegram API status/network reachability.
2. Check recent logs for `Telegram transient error` / `rate limited` / `Failed to send Telegram message`.
3. Verify bot token/chat ID are valid.

## Mitigation
- Reduce webhook volume temporarily (upstream throttling if possible).
- Keep failed deliveries for replay (do not drop payloads).
- Wait for breaker timeout window and retry with a test message.

## Recovery
1. Validate successful Telegram send.
2. Replay failed deliveries (`POST /deliveries/replay-all`).
3. Monitor error rate and breaker state for 15-30 minutes.

## Escalation
- If >30 min outage or repeated breaker flaps: escalate to on-call and check upstream Telegram/API/network issues.
