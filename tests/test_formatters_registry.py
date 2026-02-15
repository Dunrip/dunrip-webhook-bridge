from formatters import (
    get_formatter,
    get_formatter_registry,
    register_formatter,
)


def test_registry_contains_supported_events() -> None:
    registry = get_formatter_registry()
    for event_type in ["push", "pull_request", "issues", "release", "workflow_run"]:
        assert event_type in registry
        formatter = get_formatter(event_type)
        assert formatter is not None


def test_registry_returns_none_for_unknown_event() -> None:
    assert get_formatter("unknown_event") is None


def test_register_formatter_decorator_registers_callable() -> None:
    @register_formatter("unit_test_event")
    def _formatter(payload: dict) -> str:
        return f"ok:{payload.get('id', 'n/a')}"

    formatter = get_formatter("unit_test_event")
    assert formatter is not None
    assert formatter({"id": 7}) == "ok:7"


def test_register_formatter_overwrites_existing_event() -> None:
    @register_formatter("unit_test_event_overwrite")
    def _first(_: dict) -> str:
        return "first"

    @register_formatter("unit_test_event_overwrite")
    def _second(_: dict) -> str:
        return "second"

    formatter = get_formatter("unit_test_event_overwrite")
    assert formatter is not None
    assert formatter({}) == "second"


def test_registry_is_live_mapping_view() -> None:
    registry = get_formatter_registry()

    @register_formatter("unit_test_live_view")
    def _formatter(_: dict) -> str:
        return "live"

    assert "unit_test_live_view" in registry
