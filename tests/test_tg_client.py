import asyncio

import pytest
from telegram.error import NetworkError, RetryAfter

import app.services.tg_client as tg_client


def test_escape_md() -> None:
    text = "a_b*(c)."
    assert tg_client.escape_md(text) == "a\\_b\\*\\(c\\)\\."


def test_format_push_event_handles_missing_fields(monkeypatch) -> None:
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    message = tg_client.format_push_event({"commits": [{}]})
    assert "*Push*" in message
    assert "unknown" in message


def test_format_push_event_detailed_includes_commit_titles(monkeypatch) -> None:
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "detailed")
    payload = {
        "repository": {"full_name": "org/repo"},
        "pusher": {"name": "alice"},
        "ref": "refs/heads/main",
        "commits": [
            {"id": "abc123456", "message": "first commit\nwith details"},
            {"id": "def987654", "message": "second commit"},
        ],
        "compare": "https://github.com/org/repo/compare/a...b",
    }
    message = tg_client.format_push_event(payload)
    assert "• abc1234 first commit" in message
    assert "• def9876 second commit" in message


def test_format_pr_and_issue_events(monkeypatch) -> None:
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    pr_message = tg_client.format_pr_event({"action": "opened", "pull_request": {}, "repository": {}})
    issue_message = tg_client.format_issue_event({"action": "closed", "issue": {}, "repository": {}})
    assert "*Pull Request*" in pr_message
    assert "*Issue*" in issue_message


def test_compact_mode_line_cap(monkeypatch) -> None:
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "repository": {"full_name": "org/repo"},
        "pusher": {"name": "alice"},
        "ref": "refs/heads/main",
        "commits": [{"id": "abc123456", "message": "m1"}] * 8,
        "compare": "https://github.com/org/repo/compare/a...b",
    }
    message = tg_client.format_push_event(payload)
    assert 4 <= len(message.splitlines()) <= 6


def test_format_release_event(monkeypatch) -> None:
    """Test release event formatting."""
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "action": "published",
        "release": {
            "tag_name": "v2.0.0",
            "name": "Major Release",
            "html_url": "https://github.com/org/repo/releases/v2.0.0",
            "prerelease": False,
            "draft": False,
        },
        "repository": {"full_name": "org/repo"},
    }
    message = tg_client.format_release_event(payload)
    assert "*Release*" in message
    assert "Major Release" in message
    assert "View release" in message


def test_format_release_event_draft(monkeypatch) -> None:
    """Test draft release formatting."""
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "action": "published",
        "release": {
            "tag_name": "v1.0.0-beta",
            "name": "",
            "html_url": "",
            "prerelease": False,
            "draft": True,
        },
        "repository": {"full_name": "org/repo"},
    }
    message = tg_client.format_release_event(payload)
    assert "⚠️" in message
    assert "Status: draft" in message


def test_format_release_event_prerelease(monkeypatch) -> None:
    """Test prerelease formatting."""
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "action": "published",
        "release": {
            "tag_name": "v1.0.0-rc1",
            "name": "RC1",
            "html_url": "",
            "prerelease": True,
            "draft": False,
        },
        "repository": {"full_name": "org/repo"},
    }
    message = tg_client.format_release_event(payload)
    assert "⚠️" in message
    assert "Status: prerelease" in message


def test_format_workflow_run_success(monkeypatch) -> None:
    """Test workflow run success formatting."""
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "action": "completed",
        "workflow_run": {
            "conclusion": "success",
            "status": "completed",
            "head_branch": "main",
            "html_url": "https://github.com/org/repo/actions/runs/123",
        },
        "workflow": {"name": "Test Suite"},
        "repository": {"full_name": "org/repo"},
    }
    message = tg_client.format_workflow_run_event(payload)
    assert "✅" in message
    assert "Test Suite" in message
    assert "main" in message
    assert "success" in message


def test_format_workflow_run_failure(monkeypatch) -> None:
    """Test workflow run failure formatting."""
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "action": "completed",
        "workflow_run": {
            "conclusion": "failure",
            "status": "completed",
            "head_branch": "feature-branch",
            "html_url": "",
        },
        "workflow": {"name": "Build"},
        "repository": {"full_name": "org/repo"},
    }
    message = tg_client.format_workflow_run_event(payload)
    assert "❌" in message
    assert "failure" in message


def test_format_workflow_run_cancelled(monkeypatch) -> None:
    """Test cancelled workflow formatting."""
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "action": "completed",
        "workflow_run": {
            "conclusion": "cancelled",
            "status": "completed",
            "head_branch": "dev",
            "html_url": "",
        },
        "workflow": {"name": "Deploy"},
        "repository": {"full_name": "org/repo"},
    }
    message = tg_client.format_workflow_run_event(payload)
    assert "⚠️" in message


def test_sanitization_and_truncation(monkeypatch) -> None:
    monkeypatch.setattr(tg_client.settings, "message_verbosity", "compact")
    payload = {
        "action": "opened",
        "pull_request": {
            "title": "A" * 300 + "\nwith newline",
            "number": 99,
            "user": {"login": "dev_user"},
            "html_url": "javascript:alert(1)",
        },
        "repository": {"full_name": "org/repo_(weird)"},
    }
    message = tg_client.format_pr_event(payload)
    assert "javascript" not in message
    assert "\nwith newline" not in message
    assert "…" in message


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


def test_send_message_uses_settings_retries(monkeypatch) -> None:
    """Test that send_message uses settings.telegram_retries by default."""
    monkeypatch.setattr(tg_client.settings, "telegram_retries", 3)

    class CountingBot:
        def __init__(self) -> None:
            self.calls = 0

        async def send_message(self, **kwargs) -> None:
            self.calls += 1
            raise NetworkError("fail")

    bot = CountingBot()
    monkeypatch.setattr(tg_client, "bot", bot)

    async def fake_sleep(seconds: float) -> None:
        pass

    with pytest.raises(tg_client.TelegramSendError):
        asyncio.run(tg_client.send_message("hello", sleep_func=fake_sleep))

    # Should retry 3 times (4 total calls: initial + 3 retries)
    assert bot.calls == 4
