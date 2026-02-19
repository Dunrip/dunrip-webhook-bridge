"""Unified webhook dispatch logic for routing + fallback delivery."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.api.websocket import broadcaster
from app.core.exceptions import CircuitBreakerError
from app.infra.storage import Storage
from app.observability.metrics import (
    DLQ_GROWTH_TOTAL,
    PROCESSING_LATENCY,
    RETRY_TOTAL,
    ROUTE_DESTINATION_DELIVERIES,
    TELEGRAM_MESSAGES,
    WEBHOOK_LATENCY,
    WEBHOOK_REQUESTS,
)
from app.services.routing import route_event
from app.services.tg_client import TelegramSendError, send_message

logger = logging.getLogger(__name__)


async def dispatch_webhook(
    *,
    source: str,
    event_type: str,
    delivery_id: str | None,
    message: str,
    payload: dict[str, Any],
    payload_hash: str,
    storage: Storage,
    routes: list | None,
    http_client: httpx.AsyncClient | None,
    headers: dict[str, str],
    start_time: float,
) -> dict:
    """Route a webhook to destinations or fall back to Telegram-only delivery.

    Returns a response dict suitable for returning from the endpoint.
    """
    if routes:
        return await _dispatch_routed(
            source=source,
            event_type=event_type,
            delivery_id=delivery_id,
            message=message,
            payload=payload,
            payload_hash=payload_hash,
            storage=storage,
            routes=routes,
            http_client=http_client,
            headers=headers,
            start_time=start_time,
        )

    return await _dispatch_telegram_only(
        source=source,
        event_type=event_type,
        delivery_id=delivery_id,
        message=message,
        payload=payload,
        payload_hash=payload_hash,
        storage=storage,
        headers=headers,
        start_time=start_time,
    )


async def _dispatch_routed(
    *,
    source: str,
    event_type: str,
    delivery_id: str | None,
    message: str,
    payload: dict[str, Any],
    payload_hash: str,
    storage: Storage,
    routes: list,
    http_client: httpx.AsyncClient | None,
    headers: dict[str, str],
    start_time: float,
) -> dict:
    results = await route_event(
        routes,
        message,
        event_type,
        payload,
        http_client=http_client,
    )
    for result in results:
        ROUTE_DESTINATION_DELIVERIES.labels(
            destination=result.get("destination", "unknown"),
            status=result.get("status", "unknown"),
        ).inc()

    any_sent = any(r["status"] == "sent" for r in results)
    any_failed = any(r["status"] == "failed" for r in results)

    if any_sent:
        TELEGRAM_MESSAGES.labels(status="success").inc()
        if delivery_id:
            await storage.upsert_delivery_ledger(source, delivery_id, payload_hash, "delivered")
    if any_failed:
        TELEGRAM_MESSAGES.labels(status="failed").inc()
        if delivery_id:
            await storage.upsert_delivery_ledger(
                source, delivery_id, payload_hash, "failed", "partial_delivery_failure"
            )
        DLQ_GROWTH_TOTAL.labels(reason="partial_delivery_failure").inc()
        await storage.store_failed_delivery(
            source=source,
            event_type=event_type,
            payload=payload,
            headers=headers,
            error="Partial delivery failure",
            delivery_id=delivery_id,
        )

    status = "success" if any_sent else ("delivery_failed" if any_failed else "ignored")
    duration = time.time() - start_time
    WEBHOOK_REQUESTS.labels(source=source, event_type=event_type, status=status).inc()
    WEBHOOK_LATENCY.labels(source=source, event_type=event_type).observe(duration)
    PROCESSING_LATENCY.labels(source=source, event_type=event_type).observe(duration)
    logger.info(
        "webhook_delivery source=%s event_type=%s delivery_id=%s status=%s duration_ms=%.2f routed=%d",
        source,
        event_type,
        delivery_id,
        status,
        duration * 1000,
        len(results),
    )

    await broadcaster.broadcast(
        {
            "source": source,
            "event_type": event_type,
            "status": status,
            "payload": payload,
            "routing_results": results,
        }
    )

    if not any_sent and any_failed:
        raise CircuitBreakerError("Failed to deliver message", error_code="delivery_failed", status_code=502)

    return {"status": "sent", "event": event_type, "routing": results}


async def _dispatch_telegram_only(
    *,
    source: str,
    event_type: str,
    delivery_id: str | None,
    message: str,
    payload: dict[str, Any],
    payload_hash: str,
    storage: Storage,
    headers: dict[str, str],
    start_time: float,
) -> dict:
    try:
        await send_message(message)
        TELEGRAM_MESSAGES.labels(status="success").inc()
        if delivery_id:
            await storage.upsert_delivery_ledger(source, delivery_id, payload_hash, "delivered")
        WEBHOOK_REQUESTS.labels(source=source, event_type=event_type, status="success").inc()
    except TelegramSendError as exc:
        logger.exception("Telegram delivery failed for source=%s event=%s", source, event_type)
        await storage.store_failed_delivery(
            source=source,
            event_type=event_type,
            payload=payload,
            headers=headers,
            error=str(exc),
            delivery_id=delivery_id,
        )
        DLQ_GROWTH_TOTAL.labels(reason="delivery_failed").inc()
        RETRY_TOTAL.labels(classification="network").inc()
        if delivery_id:
            await storage.upsert_delivery_ledger(source, delivery_id, payload_hash, "failed", "delivery_failed")
        TELEGRAM_MESSAGES.labels(status="failed").inc()
        WEBHOOK_REQUESTS.labels(source=source, event_type=event_type, status="delivery_failed").inc()
        raise CircuitBreakerError(
            "Failed to deliver message", error_code="delivery_failed", status_code=502
        ) from exc
    finally:
        duration = time.time() - start_time
        WEBHOOK_LATENCY.labels(source=source, event_type=event_type).observe(duration)
        PROCESSING_LATENCY.labels(source=source, event_type=event_type).observe(duration)

    await broadcaster.broadcast(
        {
            "source": source,
            "event_type": event_type,
            "status": "success",
            "payload": payload,
        }
    )

    logger.info("Webhook delivered source=%s event=%s", source, event_type)
    return {"status": "sent", "event": event_type}
