import json
import logging
import time
from collections.abc import Callable
from json import JSONDecodeError
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from circuit_breaker import telegram_circuit
from config import settings
from models import GenericWebhookPayload
from security import verify_generic_token, verify_github_signature
from tg_client import (
    TelegramSendError,
    format_generic,
    format_issue_event,
    format_pr_event,
    format_push_event,
    format_release_event,
    format_workflow_run_event,
    send_message,
)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Prometheus metrics
WEBHOOK_REQUESTS = Counter(
    "webhook_requests_total",
    "Total webhook requests",
    ["source", "event_type", "status"]
)

WEBHOOK_LATENCY = Histogram(
    "webhook_request_duration_seconds",
    "Webhook request latency",
    ["source", "event_type"],
    buckets=[.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0]
)

TELEGRAM_MESSAGES = Counter(
    "telegram_messages_total",
    "Total Telegram messages sent",
    ["status"]
)

CIRCUIT_BREAKER_STATE = Counter(
    "circuit_breaker_state_changes_total",
    "Circuit breaker state changes",
    ["from_state", "to_state"]
)

EVENT_FORMATTERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "push": format_push_event,
    "pull_request": format_pr_event,
    "issues": format_issue_event,
    "release": format_release_event,
    "workflow_run": format_workflow_run_event,
}

# Simple in-memory idempotency store: delivery_id -> timestamp
_idempotency_store: dict[str, float] = {}


def _is_duplicate(delivery_id: str | None) -> bool:
    """Check if delivery_id was seen recently (within TTL)."""
    if not delivery_id:
        return False

    now = time.time()
    ttl = settings.idempotency_ttl

    # Cleanup old entries occasionally (simple probabilistic cleanup)
    if len(_idempotency_store) > 1000 and hash(delivery_id) % 10 == 0:
        cutoff = now - ttl
        expired = [k for k, v in _idempotency_store.items() if v < cutoff]
        for k in expired:
            del _idempotency_store[k]

    if delivery_id in _idempotency_store:
        age = now - _idempotency_store[delivery_id]
        if age < ttl:
            return True

    _idempotency_store[delivery_id] = now
    return False


def create_app() -> FastAPI:
    app = FastAPI(
        title="Webhook-to-Telegram Bridge",
        version="1.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.get("/metrics", tags=["monitoring"])
    async def metrics() -> PlainTextResponse:
        """Prometheus metrics endpoint."""
        return PlainTextResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Basic health check."""
        return {"status": "ok"}

    @app.get("/health/deep", tags=["health"])
    async def health_deep() -> JSONResponse:
        """Deep health check - verifies Telegram API connectivity."""
        from telegram import Bot
        from telegram.error import TelegramError

        try:
            bot = Bot(token=settings.telegram_bot_token)
            me = await bot.get_me()
            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "telegram": {
                        "connected": True,
                        "bot_username": me.username,
                    },
                    "circuit_breaker": {
                        "state": telegram_circuit.state.value,
                    },
                },
            )
        except TelegramError as exc:
            logger.warning("Deep health check failed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={
                    "status": "degraded",
                    "telegram": {"connected": False, "error": str(exc)},
                    "circuit_breaker": {
                        "state": telegram_circuit.state.value,
                    },
                },
            )

    @app.post("/webhook/github", tags=["webhooks"])
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default="ping"),
        x_github_delivery: str | None = Header(default=None),
    ) -> dict[str, str]:
        """Receive GitHub webhooks and forward to Telegram."""
        start_time = time.time()
        logger.info(
            "Received GitHub webhook event=%s delivery=%s",
            x_github_event,
            x_github_delivery,
        )

        # Idempotency check
        if _is_duplicate(x_github_delivery):
            logger.info("Duplicate delivery %s ignored", x_github_delivery)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="duplicate"
            ).inc()
            return {"status": "duplicate", "delivery_id": x_github_delivery or "unknown"}

        try:
            body = await verify_github_signature(request)
        except HTTPException as exc:
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="auth_error"
            ).inc()
            raise

        if x_github_event == "ping":
            WEBHOOK_REQUESTS.labels(
                source="github", event_type="ping", status="success"
            ).inc()
            return {"status": "pong"}

        try:
            payload = json.loads(body)
        except JSONDecodeError as exc:
            logger.warning("Malformed JSON in GitHub webhook event=%s", x_github_event)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="malformed_json"
            ).inc()
            raise HTTPException(status_code=400, detail="Malformed JSON payload") from exc

        formatter = EVENT_FORMATTERS.get(x_github_event)
        if not formatter:
            logger.info("Ignoring unsupported GitHub event=%s", x_github_event)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="ignored"
            ).inc()
            return {"status": "ignored", "event": x_github_event}

        if not isinstance(payload, dict):
            logger.warning("GitHub payload is not an object event=%s", x_github_event)
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="invalid_payload"
            ).inc()
            raise HTTPException(status_code=400, detail="Payload must be a JSON object")

        message = formatter(payload)
        try:
            await send_message(message)
            TELEGRAM_MESSAGES.labels(status="success").inc()
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="success"
            ).inc()
        except TelegramSendError as exc:
            logger.exception("Telegram delivery failed for event=%s", x_github_event)
            TELEGRAM_MESSAGES.labels(status="failed").inc()
            WEBHOOK_REQUESTS.labels(
                source="github", event_type=x_github_event, status="delivery_failed"
            ).inc()
            raise HTTPException(status_code=502, detail="Failed to deliver message") from exc
        finally:
            WEBHOOK_LATENCY.labels(
                source="github", event_type=x_github_event
            ).observe(time.time() - start_time)

        logger.info("GitHub event delivered event=%s", x_github_event)
        return {"status": "sent", "event": x_github_event}

    @app.post("/webhook/generic", tags=["webhooks"])
    async def generic_webhook(
        payload: GenericWebhookPayload,
        _token: str = Depends(verify_generic_token),
    ) -> dict[str, str]:
        """Receive generic webhooks and forward to Telegram."""
        start_time = time.time()
        logger.info("Received generic webhook title=%s", payload.title)
        message = format_generic(payload.title, payload.body, payload.url)
        try:
            await send_message(message)
            TELEGRAM_MESSAGES.labels(status="success").inc()
            WEBHOOK_REQUESTS.labels(
                source="generic", event_type="generic", status="success"
            ).inc()
        except TelegramSendError as exc:
            logger.exception("Telegram delivery failed for generic webhook")
            TELEGRAM_MESSAGES.labels(status="failed").inc()
            WEBHOOK_REQUESTS.labels(
                source="generic", event_type="generic", status="delivery_failed"
            ).inc()
            raise HTTPException(status_code=502, detail="Failed to deliver message") from exc
        finally:
            WEBHOOK_LATENCY.labels(
                source="generic", event_type="generic"
            ).observe(time.time() - start_time)

        logger.info("Generic webhook delivered")
        return {"status": "sent"}

    return app


app = create_app()
