"""Tests for destination implementations."""

import httpx
import pytest

from app.core.config import settings
from destinations.base import DestinationError
from destinations.discord import DiscordDestination, _build_embed, _strip_mdv2
from destinations.slack import SlackDestination, _build_blocks
from destinations.slack import _strip_mdv2 as _slack_strip
from destinations.telegram import TelegramDestination

# ---------------------------------------------------------------------------
# DestinationError
# ---------------------------------------------------------------------------


class TestDestinationError:
    def test_message_format(self):
        err = DestinationError("discord", "HTTP 400")
        assert str(err) == "[discord] HTTP 400"
        assert err.destination == "discord"
        assert err.classification == "unknown"
        assert err.retryable is False

    def test_extended_metadata(self):
        err = DestinationError(
            "slack",
            "HTTP 429",
            classification="rate_limit",
            retryable=True,
            retry_after_seconds=1.5,
            status_code=429,
        )
        assert err.classification == "rate_limit"
        assert err.retryable is True
        assert err.retry_after_seconds == 1.5
        assert err.status_code == 429


# ---------------------------------------------------------------------------
# TelegramDestination
# ---------------------------------------------------------------------------


class TestTelegramDestination:
    def test_name(self):
        d = TelegramDestination()
        assert d.name == "telegram"

    @pytest.mark.asyncio
    async def test_send_success(self, monkeypatch):
        calls = []

        async def fake_send(msg, **kwargs):
            calls.append(msg)

        monkeypatch.setattr("destinations.telegram.send_message", fake_send)
        d = TelegramDestination()
        await d.send("hello", event_type="push", payload={})
        assert calls == ["hello"]

    @pytest.mark.asyncio
    async def test_send_failure_raises_destination_error(self, monkeypatch):
        from app.services.tg_client import TelegramSendError

        async def fake_send(msg, **kwargs):
            raise TelegramSendError("boom")

        monkeypatch.setattr("destinations.telegram.send_message", fake_send)
        d = TelegramDestination()
        with pytest.raises(DestinationError, match="telegram"):
            await d.send("hello", event_type="push", payload={})


# ---------------------------------------------------------------------------
# Discord helpers
# ---------------------------------------------------------------------------


class TestDiscordHelpers:
    def test_strip_mdv2(self):
        assert _strip_mdv2(r"Hello \*world\*") == "Hello *world*"
        assert _strip_mdv2(r"no\_escapes") == "no_escapes"

    def test_build_embed_push(self):
        msg = "Push to repo by user\nBranch: main"
        embed = _build_embed(msg, "push", {"repository": {"full_name": "a/b"}})
        assert embed["color"] == 0x2ECC71
        assert embed["footer"]["text"] == "a/b"
        assert "Push" in embed["title"]

    def test_build_embed_unknown_event(self):
        embed = _build_embed("test", "custom", {})
        assert embed["color"] == 0x95A5A6  # grey default


# ---------------------------------------------------------------------------
# DiscordDestination
# ---------------------------------------------------------------------------


class TestDiscordDestination:
    def test_name(self):
        d = DiscordDestination("https://discord.com/api/webhooks/123/abc")
        assert d.name == "discord"

    @pytest.mark.asyncio
    async def test_send_success(self, monkeypatch):
        posted_data = []

        class FakeResponse:
            status_code = 204

            def raise_for_status(self):
                pass

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, json=None):
                posted_data.append(json)
                return FakeResponse()

        monkeypatch.setattr("destinations.discord.httpx.AsyncClient", lambda **kw: FakeClient())
        d = DiscordDestination("https://discord.com/api/webhooks/123/abc")
        await d.send("test message", event_type="push", payload={})
        assert len(posted_data) == 1
        assert "embeds" in posted_data[0]

    @pytest.mark.asyncio
    async def test_send_http_error(self, monkeypatch):
        class FakeResponse:
            status_code = 400
            text = "Bad Request"
            headers = httpx.Headers({})

            def raise_for_status(self):
                raise httpx.HTTPStatusError("err", request=None, response=self)

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, json=None):
                return FakeResponse()

        monkeypatch.setattr("destinations.discord.httpx.AsyncClient", lambda **kw: FakeClient())
        d = DiscordDestination("https://example.com/hook")
        with pytest.raises(DestinationError, match="discord") as excinfo:
            await d.send("msg", event_type="push", payload={})
        assert excinfo.value.classification == "payload_invalid"
        assert excinfo.value.retryable is False

    @pytest.mark.asyncio
    async def test_send_rate_limit_retry_then_success(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 2)
        monkeypatch.setattr(settings, "destination_retry_base_seconds", 0.01)
        monkeypatch.setattr(settings, "destination_retry_max_seconds", 0.05)

        calls = {"count": 0}

        class FakeResponse:
            def __init__(self, status_code: int, text: str = "", headers: dict[str, str] | None = None):
                self.status_code = status_code
                self.text = text
                self.headers = httpx.Headers(headers or {})

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise httpx.HTTPStatusError("err", request=None, response=self)

        class FakeClient:
            async def post(self, url, json=None):
                calls["count"] += 1
                if calls["count"] == 1:
                    return FakeResponse(429, "rate limited", {"retry-after": "0"})
                return FakeResponse(204, "ok")

        async def _no_sleep(_: float):
            return None

        monkeypatch.setattr("destinations.discord.asyncio.sleep", _no_sleep)

        d = DiscordDestination("https://example.com/hook", http_client=FakeClient())
        await d.send("msg", event_type="push", payload={})
        assert calls["count"] == 2


# ---------------------------------------------------------------------------
# Slack helpers
# ---------------------------------------------------------------------------


class TestSlackHelpers:
    def test_strip_mdv2(self):
        assert _slack_strip(r"Hello \*world\*") == "Hello *world*"

    def test_build_blocks(self):
        blocks = _build_blocks("Header line\nBody here", "push", {"repository": {"full_name": "o/r"}})
        assert blocks[0]["type"] == "header"
        assert blocks[0]["text"]["text"] == "Header line"
        assert any(b["type"] == "section" for b in blocks)
        assert any(b["type"] == "context" for b in blocks)


# ---------------------------------------------------------------------------
# SlackDestination
# ---------------------------------------------------------------------------


class TestSlackDestination:
    def test_name(self):
        d = SlackDestination("https://hooks.slack.com/services/T/B/x")
        assert d.name == "slack"

    @pytest.mark.asyncio
    async def test_send_success(self, monkeypatch):
        posted = []

        class FakeResponse:
            status_code = 200
            text = "ok"

            def raise_for_status(self):
                pass

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, json=None):
                posted.append(json)
                return FakeResponse()

        monkeypatch.setattr("destinations.slack.httpx.AsyncClient", lambda **kw: FakeClient())
        d = SlackDestination("https://hooks.slack.com/test")
        await d.send("test", event_type="generic", payload={})
        assert len(posted) == 1
        assert "blocks" in posted[0]

    @pytest.mark.asyncio
    async def test_send_failure(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 0)

        class FakeResponse:
            status_code = 500
            text = "Internal Server Error"
            headers = httpx.Headers({})

            def raise_for_status(self):
                raise httpx.HTTPStatusError("err", request=None, response=self)

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, json=None):
                return FakeResponse()

        monkeypatch.setattr("destinations.slack.httpx.AsyncClient", lambda **kw: FakeClient())
        d = SlackDestination("https://hooks.slack.com/test")
        with pytest.raises(DestinationError, match="slack") as excinfo:
            await d.send("msg", event_type="push", payload={})
        assert excinfo.value.classification == "server"
        assert excinfo.value.retryable is True

    @pytest.mark.asyncio
    async def test_send_rate_limit_retry_then_success(self, monkeypatch):
        monkeypatch.setattr(settings, "destination_max_retries", 2)
        monkeypatch.setattr(settings, "destination_retry_base_seconds", 0.01)
        monkeypatch.setattr(settings, "destination_retry_max_seconds", 0.05)

        calls = {"count": 0}

        class FakeResponse:
            def __init__(self, status_code: int, text: str = "", headers: dict[str, str] | None = None):
                self.status_code = status_code
                self.text = text
                self.headers = httpx.Headers(headers or {})

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise httpx.HTTPStatusError("err", request=None, response=self)

        class FakeClient:
            async def post(self, url, json=None):
                calls["count"] += 1
                if calls["count"] == 1:
                    return FakeResponse(429, "rate limited", {"retry-after": "0"})
                return FakeResponse(200, "ok")

        async def _no_sleep(_: float):
            return None

        monkeypatch.setattr("destinations.slack.asyncio.sleep", _no_sleep)

        d = SlackDestination("https://hooks.slack.com/test", http_client=FakeClient())
        await d.send("msg", event_type="push", payload={})
        assert calls["count"] == 2


# ---------------------------------------------------------------------------
# Destination base class / repr
# ---------------------------------------------------------------------------


class TestDestinationBase:
    def test_repr(self):
        d = TelegramDestination()
        assert "TelegramDestination" in repr(d)
        assert "telegram" in repr(d)
