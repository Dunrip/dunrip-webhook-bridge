"""Multi-destination delivery package."""

from destinations.base import Destination
from destinations.discord import DiscordDestination
from destinations.slack import SlackDestination
from destinations.telegram import TelegramDestination

__all__ = [
    "Destination",
    "DiscordDestination",
    "SlackDestination",
    "TelegramDestination",
]
