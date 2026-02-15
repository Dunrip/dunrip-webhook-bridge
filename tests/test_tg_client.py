import asyncio

import pytest
from telegram.error import NetworkError, RetryAfter

import tg_client


def test_escape_md() -> None:
    text = "a_b*(c)."
    assert tg_client.escape_md(text) == "a\\_b\\*\\(c\\)\\."


def test_format_push_event_handles_missing_fields() -> None:
    message = tg_client.format_push_event({"commits": [{}]})
    assert "*Push*" in message
    assert "unknown" in message


def test_format_pr_and_issue_events() -> None:
    pr_message = tg_client.format_pr_event({"action": "opened", "pull_request": {}, "repository": {}})
    issue_message = tg_client.format_issue_event({"action": "closed", "issue": {}, "repository": {}})
    assert "*Pull Request*" in pr_message
    assert "*Issue*" in issue_message


def test_send_message_retries_on_rate_limit(monkeypatch) -> None:
    waits: list[float] = []

    class DummyBot:
        def __init__(self) -> None:
            self.calls = 0

        async def send_message(self, **kwargs) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RetryAfter(1)

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    dummy = DummyBot()
    monkeypatch.setattr(tg_client, "bot", dummy)

    asyncio.run(tg_client.send_message("hello", retries=2, sleep_func=fake_sleep))
    assert dummy.calls == 2
    assert waits == [1.0]


def test_send_message_raises_after_network_retries(monkeypatch) -> None:
    waits: list[float] = []

    class DummyBot:
        async def send_message(self, **kwargs) -> None:
            raise NetworkError("network")

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(tg_client, "bot", DummyBot())

    with pytest.raises(tg_client.TelegramSendError):
        asyncio.run(tg_client.send_message("hello", retries=1, sleep_func=fake_sleep))

    assert waits == [1.0]
