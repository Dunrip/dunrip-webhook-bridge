# Replay Operations (Admin API)

This document clarifies the current behavior contract for replay endpoints.

## Endpoints

- `POST /deliveries/{id}/replay` — replay a single failed delivery
- `POST /deliveries/replay-all` — replay all currently failed deliveries (up to internal limits)

Both endpoints require admin auth with `replay` scope or higher.

## Behavior Contract: `POST /deliveries/replay-all`

### Previous operator expectation (historical)
Some operators treated replay-all as effectively synchronous (request returns near completion state).

### Current contract (v1.3+)
`POST /deliveries/replay-all` is **asynchronous**:

- API returns immediately with:
  - `status: "accepted"`
  - `queued: <number_of_failed_deliveries_queued_now>`
- Replay processing continues in background tasks.
- Processing concurrency is intentionally bounded to avoid overload.

Example response:

```json
{
  "status": "accepted",
  "queued": 12
}
```

## How to verify replay progress/outcome

Use these signals instead of assuming immediate completion:

1. **Delivery status API**
   - `GET /deliveries?status=failed`
   - `GET /deliveries?status=delivered`
   - `GET /deliveries?status=dead_letter`
2. **Application logs**
   - Replay attempts, state transitions, and failure reasons
3. **Health and observability**
   - `/health/deep` for runtime dependency state
   - `/metrics` for delivery/retry/failure counters

## Operational notes

- A high `queued` value means work was accepted, not completed.
- Re-triggering replay-all repeatedly during active processing may create noisy operations.
- Use targeted single-delivery replay when triaging specific failures.
- For production, prefer Redis-backed storage/rate-limit backends for durable replay metadata.
