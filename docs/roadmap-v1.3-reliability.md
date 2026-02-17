# v1.3 Reliability Roadmap

## Scope
Improve delivery reliability of inbound webhook processing from ingest through replay/operations, with serverless-safe defaults and stronger observability.

## Goals
- Fast, safe ingest path: verify -> persist/enqueue -> async processing.
- Preserve security ordering: signature verification before idempotency decisions.
- Deterministic retry lifecycle with clear dead-letter reasoning.
- Rich delivery ledger metadata to support replay safety.
- Better serverless (Vercel) behavior and docs.
- Actionable operational metrics + alerts.

## Non-goals
- Replacing destination/routing architecture.
- Building exactly-once semantics across all third-party destinations.
- Introducing breaking API changes for existing webhook producers.

## Prioritized Backlog

| Priority | Track | Issue | Effort | Notes |
|---|---|---|---|---|
| P0 | Queue-first ingest + worker | [#21](https://github.com/Dunrip/dunrip-webhook-bridge/issues/21) | L | Core reliability foundation |
| P0 | Retry lifecycle + DLQ reason codes | [#22](https://github.com/Dunrip/dunrip-webhook-bridge/issues/22) | M | Reduces noise, improves resilience |
| P0 | Delivery ledger + replay safety | [#23](https://github.com/Dunrip/dunrip-webhook-bridge/issues/23) | M | Prevents unsafe replay scenarios |
| P0 | Vercel/serverless safety pass | [#24](https://github.com/Dunrip/dunrip-webhook-bridge/issues/24) | S | Safe defaults + graceful degradation |
| P1 | Observability + ops polish | [#25](https://github.com/Dunrip/dunrip-webhook-bridge/issues/25) | S | Metrics + alert updates |

## Dependency Order
1. Track A (#21) queue-first ingest and worker loop.
2. Track B (#22) retry lifecycle over queue/processing outcomes.
3. Track C (#23) ledger metadata and replay constraints.
4. Serverless guardrails (#24) align docs/runtime with queue storage assumptions.
5. Observability polish (#25) finalize metrics and operational alerting.

## Rollout Strategy (safe defaults)
- Keep memory backend behavior backward-compatible for local/dev.
- Redis-enabled environments receive durable queue/ledger behavior.
- If Redis is unavailable while configured, degrade safely to memory with clear logs.
- Continue existing webhook endpoints and auth headers unchanged.
- Ship docs with explicit serverless guidance: Redis-backed state required for production-grade reliability.

## Validation gates
- Unit tests for queue worker happy/failure paths.
- Unit tests for retry classification and jittered backoff.
- Unit tests for ledger metadata and replay safety blocking.
- Full test suite green before merge.
