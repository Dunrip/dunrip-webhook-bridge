"""Multi-destination delivery package."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from destinations.base import Destination
from destinations.discord import DiscordDestination
from destinations.slack import SlackDestination
from destinations.telegram import TelegramDestination

DestinationFactory = Callable[..., Destination]
T = TypeVar("T", bound=Destination)


class DestinationRegistry:
    """Simple destination factory registry."""

    def __init__(self) -> None:
        self._factories: dict[str, DestinationFactory] = {}

    def register(self, name: str, factory: DestinationFactory) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("Destination name must be non-empty")
        if key in self._factories:
            raise ValueError(f"Destination {key!r} is already registered")
        self._factories[key] = factory

    def get(self, name: str) -> DestinationFactory | None:
        key = name.strip().lower()
        return self._factories.get(key)

    def list_registered(self) -> list[str]:
        return sorted(self._factories.keys())


__all__ = [
    "Destination",
    "DestinationRegistry",
    "DiscordDestination",
    "SlackDestination",
    "TelegramDestination",
]
