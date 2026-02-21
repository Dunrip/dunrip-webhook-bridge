"""Centralized Prometheus metric definitions for the webhook bridge."""

from prometheus_client import Counter, Histogram


def _get_or_create_counter(name: str, description: str, labels: list[str]) -> Counter:
    try:
        return Counter(name, description, labels)
    except ValueError:
        from prometheus_client import REGISTRY

        collector = REGISTRY._names_to_collectors.get(name)  # noqa: SLF001
        if collector is not None:
            return collector  # type: ignore[return-value]
        raise


def _get_or_create_histogram(
    name: str, description: str, labels: list[str], buckets: list[float] | None = None
) -> Histogram:
    try:
        if buckets:
            return Histogram(name, description, labels, buckets=buckets)
        return Histogram(name, description, labels)
    except ValueError:
        from prometheus_client import REGISTRY

        collector = REGISTRY._names_to_collectors.get(name)  # noqa: SLF001
        if collector is not None:
            return collector  # type: ignore[return-value]
        raise


WEBHOOK_REQUESTS = _get_or_create_counter(
    "webhook_requests_total", "Total webhook requests", ["source", "event_type", "status"]
)

WEBHOOK_LATENCY = _get_or_create_histogram(
    "webhook_request_duration_seconds",
    "Webhook request latency",
    ["source", "event_type"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0],
)

ENQUEUE_LATENCY = _get_or_create_histogram(
    "webhook_enqueue_duration_seconds",
    "Time spent validating and enqueueing webhook payloads",
    ["source"],
)

PROCESSING_LATENCY = _get_or_create_histogram(
    "webhook_processing_duration_seconds",
    "Time spent processing webhook deliveries",
    ["source", "event_type"],
)

RETRY_TOTAL = _get_or_create_counter(
    "webhook_retries_total",
    "Retry attempts by classification",
    ["classification"],
)

DLQ_GROWTH_TOTAL = _get_or_create_counter(
    "webhook_dlq_growth_total",
    "Dead-letter growth by reason",
    ["reason"],
)

TELEGRAM_MESSAGES = _get_or_create_counter("telegram_messages_total", "Total Telegram messages sent", ["status"])

CIRCUIT_BREAKER_STATE = _get_or_create_counter(
    "circuit_breaker_state_changes_total", "Circuit breaker state changes", ["from_state", "to_state"]
)

ROUTE_DESTINATION_DELIVERIES = _get_or_create_counter(
    "route_destination_deliveries_total",
    "Per-destination delivery outcomes",
    ["destination", "status"],
)

DESTINATION_DELIVERY_ATTEMPTS = _get_or_create_counter(
    "destination_delivery_attempts_total",
    "Outbound destination delivery attempts",
    ["destination"],
)

DESTINATION_DELIVERY_FAILURES = _get_or_create_counter(
    "destination_delivery_failures_total",
    "Outbound destination delivery failures by classification",
    ["destination", "classification"],
)

DESTINATION_DELIVERY_RETRIES = _get_or_create_counter(
    "destination_delivery_retries_total",
    "Outbound destination retries by classification",
    ["destination", "classification"],
)

DESTINATION_RATE_LIMIT_EVENTS = _get_or_create_counter(
    "destination_rate_limit_events_total",
    "Destination rate-limit events",
    ["destination"],
)

DESTINATION_DELIVERY_LATENCY = _get_or_create_histogram(
    "destination_delivery_duration_seconds",
    "Outbound destination delivery latency",
    ["destination"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)
