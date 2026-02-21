import httpx
import pytest

from app.core.config import settings
from destinations.base import DestinationError
from destinations.discord import DiscordDestination
from destinations.slack import SlackDestination

pytestmark = pytest.mark.integration


async def _no_sleep(_: float) -> None:
    return None


def _mock_client(
    status_codes: list[int], *, retry_after: str | None = None
) -> tuple[httpx.AsyncClient, dict[str, int]]:
    calls = {"count": 0}

    async def _handler(request: httpx.Request) -> httpx.Response:
        idx = min(calls["count"], len(status_codes) - 1)
        calls["count"] += 1
        code = status_codes[idx]
        headers = {"retry-after": retry_after} if code == 429 and retry_after is not None else None
        return httpx.Response(code, headers=headers)

    transport = httpx.MockTransport(_handler)
    return httpx.AsyncClient(transport=transport, timeout=1.0), calls


class TestDiscordWebhookIntegration:
    @pytest.mark.asyncio
    async def test_discord_2xx_success(self):
        client, calls = _mock_client([204])
        try:
            destination = DiscordDestination("https://discord.com/api/webhooks/1/token", http_client=client)
            await destination.send("ok", event_type="push", payload={})
            assert calls["count"] == 1
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_discord_4xx_classified_payload_invalid(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 0)
        client, _ = _mock_client([400])
        try:
            destination = DiscordDestination("https://discord.com/api/webhooks/1/token", http_client=client)
            with pytest.raises(DestinationError) as exc:
                await destination.send("bad", event_type="push", payload={})
            assert exc.value.classification == "payload_invalid"
            assert exc.value.retryable is False
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_discord_429_retries_then_success(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 2)
        monkeypatch.setattr(settings, "destination_retry_base_seconds", 0.01)
        monkeypatch.setattr(settings, "destination_retry_max_seconds", 0.05)
        monkeypatch.setattr("destinations.discord.asyncio.sleep", _no_sleep)

        client, calls = _mock_client([429, 204], retry_after="0")
        try:
            destination = DiscordDestination("https://discord.com/api/webhooks/1/token", http_client=client)
            await destination.send("retry", event_type="push", payload={})
            assert calls["count"] == 2
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_discord_5xx_retries_and_fails(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 1)
        monkeypatch.setattr(settings, "destination_retry_base_seconds", 0.01)
        monkeypatch.setattr(settings, "destination_retry_max_seconds", 0.05)
        monkeypatch.setattr("destinations.discord.asyncio.sleep", _no_sleep)

        client, calls = _mock_client([500, 500])
        try:
            destination = DiscordDestination("https://discord.com/api/webhooks/1/token", http_client=client)
            with pytest.raises(DestinationError) as exc:
                await destination.send("retry", event_type="push", payload={})
            assert exc.value.classification == "server"
            assert exc.value.retryable is True
            assert calls["count"] == 2
        finally:
            await client.aclose()


class TestSlackWebhookIntegration:
    @pytest.mark.asyncio
    async def test_slack_2xx_success(self):
        client, calls = _mock_client([200])
        try:
            destination = SlackDestination("https://hooks.slack.com/services/T/B/X", http_client=client)
            await destination.send("ok", event_type="push", payload={})
            assert calls["count"] == 1
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_slack_4xx_classified_payload_invalid(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 0)
        client, _ = _mock_client([400])
        try:
            destination = SlackDestination("https://hooks.slack.com/services/T/B/X", http_client=client)
            with pytest.raises(DestinationError) as exc:
                await destination.send("bad", event_type="push", payload={})
            assert exc.value.classification == "payload_invalid"
            assert exc.value.retryable is False
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_slack_429_retries_then_success(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 2)
        monkeypatch.setattr(settings, "destination_retry_base_seconds", 0.01)
        monkeypatch.setattr(settings, "destination_retry_max_seconds", 0.05)
        monkeypatch.setattr("destinations.slack.asyncio.sleep", _no_sleep)

        client, calls = _mock_client([429, 200], retry_after="0")
        try:
            destination = SlackDestination("https://hooks.slack.com/services/T/B/X", http_client=client)
            await destination.send("retry", event_type="push", payload={})
            assert calls["count"] == 2
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_slack_5xx_retries_and_fails(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 1)
        monkeypatch.setattr(settings, "destination_retry_base_seconds", 0.01)
        monkeypatch.setattr(settings, "destination_retry_max_seconds", 0.05)
        monkeypatch.setattr("destinations.slack.asyncio.sleep", _no_sleep)

        client, calls = _mock_client([503, 503])
        try:
            destination = SlackDestination("https://hooks.slack.com/services/T/B/X", http_client=client)
            with pytest.raises(DestinationError) as exc:
                await destination.send("retry", event_type="push", payload={})
            assert exc.value.classification == "server"
            assert exc.value.retryable is True
            assert calls["count"] == 2
        finally:
            await client.aclose()
