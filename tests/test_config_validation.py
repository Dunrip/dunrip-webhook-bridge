from app.core.config import Settings


def _base_kwargs() -> dict[str, str]:
    return {
        "telegram_bot_token": "test",
        "telegram_chat_id": "123",
        "github_webhook_secret": "secret",
        "generic_webhook_token": "generic",
    }


def test_discord_webhook_url_validation_accepts_valid_url():
    settings = Settings(**_base_kwargs(), discord_webhook_url="https://discord.com/api/webhooks/1/abc")
    assert settings.discord_webhook_url.startswith("https://discord.com/api/webhooks/")


def test_discord_webhook_url_validation_rejects_invalid_path():
    try:
        Settings(**_base_kwargs(), discord_webhook_url="https://discord.com/not-webhooks")
    except Exception as exc:  # pydantic validation error type
        assert "/api/webhooks/" in str(exc)
    else:
        raise AssertionError("Expected invalid discord webhook URL to fail validation")


def test_slack_webhook_url_validation_rejects_non_slack_host():
    try:
        Settings(**_base_kwargs(), slack_webhook_url="https://example.com/services/T/B/XXX")
    except Exception as exc:
        assert "slack.com" in str(exc)
    else:
        raise AssertionError("Expected invalid slack webhook host to fail validation")


def test_routes_strict_validation_default_false():
    settings = Settings(**_base_kwargs())
    assert settings.routes_strict_validation is False
