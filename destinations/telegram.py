"""Telegram destination - wraps existing tg_client.send_message."""

from __future__ import annotations

from typing import Any

from app.services.tg_client import TelegramSendError, send_message
from destinations.base import Destination, DestinationError


class TelegramDestination(Destination):
    """Delivers messages to Telegram via the existing bot client."""

    @property
    def name(self) -> str:
        return "telegram"

    async def send(self, message: str, *, event_type: str, payload: dict[str, Any]) -> None:
        try:
            await send_message(message)
        except TelegramSendError as exc:
            raise DestinationError("telegram", str(exc)) from exc
