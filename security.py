import hashlib
import hmac
import logging
from functools import partial

import anyio
from fastapi import Header, HTTPException, Request

from config import settings

logger = logging.getLogger(__name__)


def _compute_signature(body: bytes, secret: str) -> str:
    """Synchronous HMAC computation (run in thread pool)."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def verify_github_signature(request: Request) -> bytes:
    """Validate GitHub webhook HMAC-SHA256 signature. Returns raw body."""
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("GitHub webhook missing signature header")
        raise HTTPException(status_code=401, detail="Missing signature header")

    body = await request.body()

    # Body size limit
    if len(body) > settings.max_body_size:
        logger.warning(
            "GitHub webhook body too large: %d bytes (max %d)",
            len(body),
            settings.max_body_size,
        )
        raise HTTPException(status_code=413, detail="Payload too large")

    # Run HMAC in thread pool to avoid blocking event loop
    expected = await anyio.to_thread.run_sync(
        partial(_compute_signature, body, settings.github_webhook_secret)
    )

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
