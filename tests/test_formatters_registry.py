from formatters import get_formatter, get_formatter_registry


def test_registry_contains_supported_events() -> None:
    registry = get_formatter_registry()
    for event_type in ["push", "pull_request", "issues", "release", "workflow_run"]:
        assert event_type in registry
        formatter = get_formatter(event_type)
        assert formatter is not None


def test_registry_returns_none_for_unknown_event() -> None:
    assert get_formatter("unknown_event") is None
