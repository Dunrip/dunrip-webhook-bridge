from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeAlias

from tg_client import (
    format_issue_event,
    format_pr_event,
    format_push_event,
    format_release_event,
    format_workflow_run_event,
)


class Formatter(Protocol):
    """Callable formatter contract for GitHub webhook payloads."""

    def __call__(self, payload: Mapping[str, Any]) -> str: ...


FormatterMap: TypeAlias = dict[str, Formatter]

_FORMATTERS: FormatterMap = {}


def register_formatter(event_type: str) -> Callable[[Formatter], Formatter]:
    """Register a formatter for an event type using a uniform decorator API."""

    def decorator(formatter: Formatter) -> Formatter:
        _FORMATTERS[event_type] = formatter
        return formatter

    return decorator


def get_formatter(event_type: str) -> Formatter | None:
    """Return formatter for event type, if one is registered."""
    return _FORMATTERS.get(event_type)


def get_formatter_registry() -> Mapping[str, Formatter]:
    """Read-only view of the formatter registry."""
    return _FORMATTERS


# Built-in GitHub formatters
register_formatter("push")(format_push_event)
register_formatter("pull_request")(format_pr_event)
register_formatter("issues")(format_issue_event)
register_formatter("release")(format_release_event)
register_formatter("workflow_run")(format_workflow_run_event)
