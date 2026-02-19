# Destination Plugins

This project supports destination plugins through the routing destination registry.

## Destination contract

A destination must implement `destinations.base.Destination`:

- `name` property
- `async send(message: str, *, event_type: str, payload: dict) -> None`
- raise `DestinationError` on delivery failure

## Minimal plugin template

```python
from typing import Any

import httpx

from destinations.base import Destination, DestinationError


class CustomWebhookDestination(Destination):
    def __init__(self, webhook_url: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._webhook_url = webhook_url
        self._http_client = http_client

    @property
    def name(self) -> str:
        return "custom_webhook"

    async def send(self, message: str, *, event_type: str, payload: dict[str, Any]) -> None:
        body = {"text": message, "event_type": event_type, "payload": payload}
        try:
            if self._http_client is not None:
                resp = await self._http_client.post(self._webhook_url, json=body)
                resp.raise_for_status()
                return
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._webhook_url, json=body)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DestinationError("custom_webhook", str(exc)) from exc
```

## Registration snippet

```python
from app.services.routing import register_destination
from plugins.custom_webhook import CustomWebhookDestination


def register_plugins() -> None:
    register_destination(
        "custom_webhook",
        lambda **kwargs: CustomWebhookDestination(
            webhook_url="https://example.internal/hook",
            http_client=kwargs.get("http_client"),
        ),
    )
```

Call your plugin registration during app startup before webhook traffic begins.

## Feature flags

Set `DESTINATION_FEATURE_FLAGS` to selectively enable destinations:

```bash
DESTINATION_FEATURE_FLAGS="telegram=true,discord=false,slack=true,custom_webhook=true"
```

Disabled destinations are treated as skipped (safe fallback behavior).
