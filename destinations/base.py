"""Abstract base class for webhook destinations."""

from __future__ import annotations

import abc
from typing import Any


class Destination(abc.ABC):
    """Interface that every delivery destination must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable destination name (e.g. 'telegram', 'discord')."""

    @abc.abstractmethod
    async def send(self, message: str, *, event_type: str, payload: dict[str, Any]) -> None:
        """Deliver *message* to this destination.

        Args:
            message: Pre-formatted text (MarkdownV2 for Telegram, plain for others).
            event_type: GitHub event type or "generic".
            payload: Original webhook payload dict.

        Raises:
            DestinationError: If delivery fails after retries.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"


class DestinationError(RuntimeError):
    """Raised when a destination fails to deliver a message."""

    def __init__(self, destination: str, detail: str) -> None:
        self.destination = destination
        super().__init__(f"[{destination}] {detail}")
