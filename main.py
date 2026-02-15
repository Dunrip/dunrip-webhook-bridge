import json
import logging

from fastapi import Depends, FastAPI, Header, Request

from config import settings
from models import GenericWebhookPayload
from security import verify_generic_token, verify_github_signature
from telegram import (
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

app = FastAPI(title="Webhook-to-Telegram Bridge", version="1.0.0")

EVENT_FORMATTERS = {
    "push": format_push_event,
    "pull_request": format_pr_event,
    "issues": format_issue_event,
}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default="ping"),
):
    body = await verify_github_signature(request)

    if x_github_event == "ping":
        return {"status": "pong"}

    payload = json.loads(body)
    formatter = EVENT_FORMATTERS.get(x_github_event)
    if not formatter:
        logger.info("Ignoring unsupported event: %s", x_github_event)
        return {"status": "ignored", "event": x_github_event}

    message = formatter(payload)
    await send_message(message)
    return {"status": "sent", "event": x_github_event}


@app.post("/webhook/generic")
async def generic_webhook(
    payload: GenericWebhookPayload,
    _token: str = Depends(verify_generic_token),
):
    message = format_generic(payload.title, payload.body, payload.url)
    await send_message(message)
    return {"status": "sent"}
