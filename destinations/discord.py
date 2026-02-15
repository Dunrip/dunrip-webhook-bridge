"""Discord webhook destination - sends embeds via Discord webhook URL."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from destinations.base import Destination, DestinationError

logger = logging.getLogger(__name__)

# Strip MarkdownV2 escapes (backslash before special chars)
_MD_ESCAPE_RE = re.compile(r"\\([_*\[\]()~`>#+\-=|{}.!\\])")


def _strip_mdv2(text: str) -> str:
    """Convert Telegram MarkdownV2 to plain text for Discord."""
    return _MD_ESCAPE_RE.sub(r"\1", text)


def _build_embed(message: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Discord embed from the formatted message and payload."""
    repo = ""
    if isinstance(payload.get("repository"), dict):
        repo = payload["repository"].get("full_name", "")

    color_map = {
        "push": 0x2ECC71,            # green
        "pull_request": 0x3498DB,     # blue
        "issues": 0xE67E22,           # orange
        "release": 0x9B59B6,          # purple
        "workflow_run": 0x1ABC9C,     # teal
        "generic": 0x95A5A6,          # grey
    }

    plain = _strip_mdv2(message)
    lines = plain.strip().split("\n")
    title = lines[0] if lines else event_type
    description = "\n".join(lines[1:]) if len(lines) > 1 else ""

    embed: dict[str, Any] = {
        "title": title[:256],
        "description": description[:4096],
        "color": color_map.get(event_type, 0x95A5A6),
    }
    if repo:
        embed["footer"] = {"text": repo}

    return embed


class DiscordDestination(Destination):
    """Delivers messages to a Discord channel via incoming webhook."""

    def __init__(self, webhook_url: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._webhook_url = webhook_url
        self._http_client = http_client

    @property
    def name(self) -> str:
        return "discord"

    async def send(self, message: str, *, event_type: str, payload: dict[str, Any]) -> None:
        embed = _build_embed(message, event_type, payload)
        body = {"embeds": [embed]}

        try:
            if self._http_client is not None:
                resp = await self._http_client.post(self._webhook_url, json=body)
                resp.raise_for_status()
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(self._webhook_url, json=body)
                    resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Discord webhook returned %s: %s", exc.response.status_code, exc.response.text[:200])
            raise DestinationError("discord", f"HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            logger.error("Discord webhook request failed: %s", exc)
            raise DestinationError("discord", str(exc)) from exc
