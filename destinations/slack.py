"""Slack incoming-webhook destination."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from app.core.config import settings
from destinations.base import Destination, DestinationError

logger = logging.getLogger(__name__)

_MD_ESCAPE_RE = re.compile(r"\\([_*\[\]()~`>#+\-=|{}.!\\])")


def _strip_mdv2(text: str) -> str:
    """Convert Telegram MarkdownV2 to plain text for Slack."""
    return _MD_ESCAPE_RE.sub(r"\1", text)


def _retry_after_seconds(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _classify_http_status(status_code: int) -> tuple[str, bool]:
    if status_code == 429:
        return "rate_limit", True
    if status_code in {401, 403}:
        return "auth", False
    if status_code in {400, 404, 410, 413, 422}:
        return "payload_invalid", False
    if 500 <= status_code <= 599:
        return "server", True
    return "http_error", False


def _retry_delay(attempt: int, retry_after_seconds: float | None) -> float:
    if retry_after_seconds is not None:
        return min(retry_after_seconds, settings.destination_retry_max_seconds)
    base = settings.destination_retry_base_seconds
    return min(base * (2**attempt), settings.destination_retry_max_seconds)


def _build_blocks(message: str, event_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Slack Block Kit blocks from the formatted message."""
    plain = _strip_mdv2(message)
    lines = plain.strip().split("\n")
    header_text = lines[0] if lines else event_type
    body_text = "\n".join(lines[1:]) if len(lines) > 1 else ""

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text[:150]},
        },
    ]
    if body_text:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body_text[:3000]},
            }
        )

    repo = ""
    if isinstance(payload.get("repository"), dict):
        repo = payload["repository"].get("full_name", "")
    if repo:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{repo}_ | {event_type}"}],
            }
        )

    return blocks


class SlackDestination(Destination):
    """Delivers messages to Slack via an incoming webhook URL."""

    def __init__(self, webhook_url: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._webhook_url = webhook_url
        self._http_client = http_client

    @property
    def name(self) -> str:
        return "slack"

    async def _post_with_retries(self, client: httpx.AsyncClient, body: dict[str, Any]) -> None:
        max_attempts = settings.destination_max_retries + 1

        for attempt in range(max_attempts):
            try:
                resp = await client.post(self._webhook_url, json=body)
                resp.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                classification, retryable = _classify_http_status(status_code)
                retry_after = _retry_after_seconds(exc.response.headers)

                if retryable and attempt < max_attempts - 1:
                    delay = _retry_delay(attempt, retry_after)
                    logger.warning(
                        "Slack delivery retry destination=%s status=%s attempt=%s/%s delay=%.2fs",
                        self.name,
                        status_code,
                        attempt + 1,
                        max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error("Slack webhook returned %s: %s", status_code, exc.response.text[:200])
                raise DestinationError(
                    "slack",
                    f"HTTP {status_code}",
                    classification=classification,
                    retryable=retryable,
                    retry_after_seconds=retry_after,
                    status_code=status_code,
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < max_attempts - 1:
                    delay = _retry_delay(attempt, None)
                    logger.warning(
                        "Slack delivery network retry destination=%s attempt=%s/%s delay=%.2fs error=%s",
                        self.name,
                        attempt + 1,
                        max_attempts,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error("Slack webhook request failed: %s", exc)
                raise DestinationError("slack", str(exc), classification="network", retryable=True) from exc

    async def send(self, message: str, *, event_type: str, payload: dict[str, Any]) -> None:
        blocks = _build_blocks(message, event_type, payload)
        plain = _strip_mdv2(message)
        body = {"text": plain[:3000], "blocks": blocks}

        if self._http_client is not None:
            await self._post_with_retries(self._http_client, body)
            return

        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            await self._post_with_retries(client, body)
