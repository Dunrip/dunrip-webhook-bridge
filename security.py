import hashlib
import hmac

from fastapi import Header, HTTPException, Request

from config import settings


async def verify_github_signature(request: Request) -> bytes:
    """Validate GitHub webhook HMAC-SHA256 signature. Returns raw body."""
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise HTTPException(status_code= 401, detail="Missing signature header")

    body = await request.body()
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code= 401, detail="Invalid signature")

    return body


def verify_generic_token(x_webhook_token: str = Header()) -> str:
    """Validate bearer token for generic webhooks."""
    if not hmac.compare_digest(x_webhook_token, settings.generic_webhook_token):
        raise HTTPException(status_code= 401, detail="Invalid token")
    return x_webhook_token
