import json
import logging
from json import JSONDecodeError
from typing import Any
from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from config import settings
from models import GenericWebhookPayload
from security import verify_generic_token, verify_github_signature
from tg_client import (
    TelegramSendError,
    format_generic,
    format_issue_event,
    format_pr_event,
    format_push_event,
    send_message,
)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

EVENT_FORMATTERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "push": format_push_event,
    "pull_request": format_pr_event,
    "issues": format_issue_event,
}


def create_app() -> FastAPI:
    app = FastAPI(title="Webhook-to-Telegram Bridge", version="1.0.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook/github")
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default="ping"),
    ) -> dict[str, str]:
        logger.info("Received GitHub webhook event=%s", x_github_event)

        body = await verify_github_signature(request)

        if x_github_event == "ping":
            return {"status": "pong"}

        try:
            payload = json.loads(body)
        except JSONDecodeError as exc:
            logger.warning("Malformed JSON in GitHub webhook event=%s", x_github_event)
            raise HTTPException(status_code=400, detail="Malformed JSON payload") from exc

        formatter = EVENT_FORMATTERS.get(x_github_event)
        if not formatter:
            logger.info("Ignoring unsupported GitHub event=%s", x_github_event)
            return {"status": "ignored", "event": x_github_event}

        if not isinstance(payload, dict):
            logger.warning("GitHub payload is not an object event=%s", x_github_event)
            raise HTTPException(status_code=400, detail="Payload must be a JSON object")

        message = formatter(payload)
        try:
            await send_message(message)
        except TelegramSendError as exc:
            logger.exception("Telegram delivery failed for event=%s", x_github_event)
            raise HTTPException(status_code=502, detail="Failed to deliver message") from exc

        logger.info("GitHub event delivered event=%s", x_github_event)
        return {"status": "sent", "event": x_github_event}

    @app.post("/webhook/generic")
    async def generic_webhook(
        payload: GenericWebhookPayload,
        _token: str = Depends(verify_generic_token),
    ) -> dict[str, str]:
        logger.info("Received generic webhook title=%s", payload.title)
        message = format_generic(payload.title, payload.body, payload.url)
        try:
            await send_message(message)
        except TelegramSendError as exc:
            logger.exception("Telegram delivery failed for generic webhook")
            raise HTTPException(status_code=502, detail="Failed to deliver message") from exc
        logger.info("Generic webhook delivered")
        return {"status": "sent"}

    return app


app = create_app()
