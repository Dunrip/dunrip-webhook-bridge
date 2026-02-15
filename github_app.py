"""GitHub App integration for automatic webhook registration.

Provides an OAuth callback endpoint (``/github/install``) that exchanges an
installation code for an access token and can register webhooks automatically.

Requires ``GITHUB_APP_ID`` and ``GITHUB_APP_PRIVATE_KEY`` to be set.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Query

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github-app"])


def _generate_jwt() -> str:
    """Generate a short-lived JWT for GitHub App authentication."""
    if not settings.github_app_id or not settings.github_app_private_key:
        raise HTTPException(status_code=501, detail="GitHub App not configured")

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, settings.github_app_private_key, algorithm="RS256")


async def _get_installation_token(installation_id: int) -> dict[str, Any]:
    """Exchange an installation ID for an access token."""
    token = _generate_jwt()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()


@router.get("/install")
async def github_install_callback(
    installation_id: int = Query(...),
    setup_action: str = Query(default="install"),
) -> dict[str, Any]:
    """OAuth callback for GitHub App installation.

    GitHub redirects here after a user installs the App on their account /
    organisation.  We exchange the *installation_id* for an access token and
    return summary info.
    """
    try:
        token_data = await _get_installation_token(installation_id)
    except httpx.HTTPStatusError as exc:
        logger.error("GitHub token exchange failed: %s", exc.response.text[:300])
        raise HTTPException(status_code=502, detail="Failed to exchange installation token") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during GitHub App install")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return {
        "status": "installed",
        "setup_action": setup_action,
        "installation_id": installation_id,
        "token_expires_at": token_data.get("expires_at"),
        "permissions": token_data.get("permissions", {}),
    }
