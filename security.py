import hashlib
import hmac
import logging

from fastapi import Header, HTTPException, Request

from config import settings

logger = logging.getLogger(__name__)


async def verify_github_signature(request: Request) -> bytes:
    """Validate GitHub webhook HMAC-SHA256 signature. Returns raw body."""
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("GitHub webhook missing signature header")
        raise HTTPException(status_code=401, detail="Missing signature header")

    body = await request.body()
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        logger.warning("GitHub webhook signature validation failed")
        raise HTTPException(status_code=401, detail="Invalid signature")

    return body


def verify_generic_token(x_webhook_token: str | None = Header(default=None)) -> str:
    """Validate bearer token for generic webhooks."""
    if x_webhook_token is None:
        logger.warning("Generic webhook missing token header")
        raise HTTPException(status_code=401, detail="Missing token header")

    if not hmac.compare_digest(x_webhook_token, settings.generic_webhook_token):
        logger.warning("Generic webhook token validation failed")
        raise HTTPException(status_code=401, detail="Invalid token")
    return x_webhook_token
