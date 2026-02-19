"""Example destination plugin: custom webhook destination."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.routing import register_destination
from destinations.base import Destination, DestinationError


class CustomWebhookDestination(Destination):
    def __init__(self, webhook_url: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._webhook_url = webhook_url
        self._http_client = http_client

    @property
    def name(self) -> str:
        return "custom_webhook"

    async def send(self, message: str, *, event_type: str, payload: dict[str, Any]) -> None:
        body = {
            "text": message,
            "event_type": event_type,
            "repository": payload.get("repository", {}),
        }
        try:
            if self._http_client is not None:
                response = await self._http_client.post(self._webhook_url, json=body)
                response.raise_for_status()
                return
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self._webhook_url, json=body)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DestinationError("custom_webhook", str(exc)) from exc


def register_example_plugin(webhook_url: str) -> None:
    """Register this example destination into the global routing registry."""
    register_destination(
        "custom_webhook",
        lambda **kwargs: CustomWebhookDestination(
            webhook_url=webhook_url,
            http_client=kwargs.get("http_client"),
        ),
    )
