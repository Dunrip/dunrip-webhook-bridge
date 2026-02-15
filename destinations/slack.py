"""Slack incoming-webhook destination."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from destinations.base import Destination, DestinationError

logger = logging.getLogger(__name__)

_MD_ESCAPE_RE = re.compile(r"\\([_*\[\]()~`>#+\-=|{}.!\\])")


def _strip_mdv2(text: str) -> str:
    """Convert Telegram MarkdownV2 to plain text for Slack."""
    return _MD_ESCAPE_RE.sub(r"\1", text)


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

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    @property
    def name(self) -> str:
        return "slack"

    async def send(self, message: str, *, event_type: str, payload: dict[str, Any]) -> None:
        blocks = _build_blocks(message, event_type, payload)
        plain = _strip_mdv2(message)
        body = {"text": plain[:3000], "blocks": blocks}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._webhook_url, json=body)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Slack webhook returned %s: %s", exc.response.status_code, exc.response.text[:200])
            raise DestinationError("slack", f"HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            logger.error("Slack webhook request failed: %s", exc)
            raise DestinationError("slack", str(exc)) from exc
