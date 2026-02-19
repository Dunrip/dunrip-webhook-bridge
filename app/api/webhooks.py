"""Webhook endpoint handlers for GitHub and generic payloads."""

from __future__ import annotations

import json
import logging
import time
from json import JSONDecodeError

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from app.core.errors import ErrorCode
from app.core.exceptions import ValidationError, WebhookError
from app.core.security import verify_generic_token, verify_github_signature
from app.infra.storage import Storage
from app.models.models import GenericWebhookPayload
from app.observability.metrics import ENQUEUE_LATENCY, WEBHOOK_REQUESTS
from app.services.formatters import get_formatter
from app.services.reliability import payload_hash
from app.services.tg_client import format_generic
from app.services.webhook_dispatch import dispatch_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _error_response(request: Request, status_code: int, code: ErrorCode | str, message: str) -> JSONResponse:
    """Build a standardized JSON error response payload."""
    rid = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"error": str(code), "message": message, "request_id": rid},
        headers={"X-Request-ID": rid},
    )


def _get_storage(request: Request) -> Storage:
    from app.main import _initialize_app_state

    _initialize_app_state(request.app)
    return request.app.state.storage


@router.post("/webhook/github", response_model=None)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default="ping"),
    x_github_delivery: str | None = Header(default=None),
    storage: Storage = Depends(_get_storage),
) -> dict | JSONResponse:
    """Receive GitHub webhooks and forward to Telegram."""
    start_time = time.time()
    logger.info(
        "webhook_received source=github event_type=%s delivery_id=%s",
        x_github_event,
        x_github_delivery,
    )

    try:
        body = await verify_github_signature(request)
    except WebhookError:
        WEBHOOK_REQUESTS.labels(source="github", event_type=x_github_event, status="auth_error").inc()
        raise

    request_start = time.time()
    body_hash = payload_hash(body)
    if x_github_delivery:
        existing = await storage.get_delivery_ledger("github", x_github_delivery)
        if existing and existing.get("payload_hash") != body_hash:
            WEBHOOK_REQUESTS.labels(source="github", event_type=x_github_event, status="replay_rejected").inc()
            return _error_response(
                request, 409, "replay_mismatch", "Delivery id already seen with different payload hash"
            )
        await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "received")

    # Idempotency check (after signature verification to prevent poisoning)
    if await storage.is_duplicate_delivery(x_github_delivery):
        logger.warning(
            "webhook_duplicate source=github event_type=%s delivery_id=%s", x_github_event, x_github_delivery
        )
        WEBHOOK_REQUESTS.labels(source="github", event_type=x_github_event, status="duplicate").inc()
        if x_github_delivery:
            await storage.upsert_delivery_ledger("github", x_github_delivery, body_hash, "duplicate")
        return _error_response(
            request,
            409,
            "duplicate_delivery",
            f"Duplicate delivery: {x_github_delivery or 'unknown'}",
        )

    ENQUEUE_LATENCY.labels(source="github").observe(time.time() - request_start)

    if x_github_event == "ping":
        WEBHOOK_REQUESTS.labels(source="github", event_type="ping", status="success").inc()
        return {"status": "pong"}

    try:
        payload = json.loads(body)
    except JSONDecodeError as exc:
        logger.warning("Malformed JSON in GitHub webhook event=%s", x_github_event)
        WEBHOOK_REQUESTS.labels(source="github", event_type=x_github_event, status="malformed_json").inc()
        raise ValidationError("Malformed JSON payload", error_code="malformed_json") from exc

    formatter = get_formatter(x_github_event)
    if not formatter:
        logger.info("Ignoring unsupported GitHub event=%s", x_github_event)
        WEBHOOK_REQUESTS.labels(source="github", event_type=x_github_event, status="ignored").inc()
        return {"status": "ignored", "event": x_github_event}

    if not isinstance(payload, dict):
        logger.warning("GitHub payload is not an object event=%s", x_github_event)
        WEBHOOK_REQUESTS.labels(source="github", event_type=x_github_event, status="invalid_payload").inc()
        raise ValidationError("Payload must be a JSON object")

    message = formatter(payload)

    return await dispatch_webhook(
        source="github",
        event_type=x_github_event,
        delivery_id=x_github_delivery,
        message=message,
        payload=payload,
        payload_hash=body_hash,
        storage=storage,
        routes=request.app.state.routes,
        http_client=request.app.state.http,
        headers={
            "x-github-event": x_github_event,
            "x-github-delivery": x_github_delivery or "",
        },
        start_time=start_time,
    )


@router.post("/webhook/generic", response_model=None)
async def generic_webhook(
    request: Request,
    payload: GenericWebhookPayload,
    _token: str = Depends(verify_generic_token),
    storage: Storage = Depends(_get_storage),
) -> dict:
    """Receive generic webhooks and forward to Telegram."""
    start_time = time.time()
    request_start = time.time()
    logger.info("webhook_received source=generic event_type=generic title=%s", payload.title)
    message = format_generic(payload.title, payload.body, payload.url)
    payload_dict = payload.model_dump()
    generic_delivery_id = _request_id(request)
    generic_hash = payload_hash(payload_dict)
    await storage.upsert_delivery_ledger("generic", generic_delivery_id, generic_hash, "received")
    ENQUEUE_LATENCY.labels(source="generic").observe(time.time() - request_start)

    return await dispatch_webhook(
        source="generic",
        event_type="generic",
        delivery_id=generic_delivery_id,
        message=message,
        payload=payload_dict,
        payload_hash=generic_hash,
        storage=storage,
        routes=request.app.state.routes,
        http_client=request.app.state.http,
        headers={"x-request-id": generic_delivery_id},
        start_time=start_time,
    )
