"""YAML-based routing engine for multi-destination webhook delivery.

Routes are loaded from a YAML file (``ROUTES_YAML`` env var) or inline YAML
string and evaluated against each incoming webhook event.  Each matching route
sends the formatted message to its configured destination(s).

Example YAML config (see also ``examples/routes.yaml``)::

    routes:
      - name: all-to-telegram
        destination: telegram
      - name: releases-to-discord
        filter:
          event_type: release
        destination: discord
      - name: main-pushes-to-slack
        filter:
          event_type: push
          branch: main
        destination: slack
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

from app.core.config import settings
from destinations import DestinationRegistry
from destinations.base import Destination, DestinationError
from destinations.discord import DiscordDestination
from destinations.slack import SlackDestination
from destinations.telegram import TelegramDestination

logger = logging.getLogger(__name__)


def _destination_flags() -> dict[str, bool]:
    """Parse DESTINATION_FEATURE_FLAGS-like CSV from settings.

    Format: "telegram=true,discord=false".
    Unknown values default to enabled.
    """
    raw = getattr(settings, "destination_feature_flags", "")
    flags: dict[str, bool] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        normalized = value.strip().lower()
        enabled = normalized in {"1", "true", "yes", "on"}
        flags[name.strip().lower()] = enabled
    return flags


def _is_destination_enabled(name: str) -> bool:
    return _destination_flags().get(name.strip().lower(), True)


@dataclass
class RouteFilter:
    """Criteria that must all match for a route to fire."""

    event_type: str | None = None
    repo: str | None = None
    branch: str | None = None

    def matches(self, event_type: str, payload: dict[str, Any]) -> bool:
        if self.event_type and self.event_type != event_type:
            return False

        if self.repo:
            repository = payload.get("repository")
            if isinstance(repository, dict):
                full_name = repository.get("full_name", "")
            else:
                full_name = ""
            if self.repo != full_name:
                return False

        if self.branch:
            branch = _extract_branch(event_type, payload)
            if self.branch != branch:
                return False

        return True


@dataclass
class Route:
    """A single routing rule mapping filter criteria to a destination."""

    name: str
    destination_name: str
    filter: RouteFilter = field(default_factory=RouteFilter)


def _extract_branch(event_type: str, payload: dict[str, Any]) -> str:
    """Best-effort branch extraction from various GitHub event payloads."""
    if event_type == "push":
        ref = str(payload.get("ref", ""))
        return ref.removeprefix("refs/heads/")
    pr = payload.get("pull_request")
    if isinstance(pr, dict):
        base = pr.get("base")
        if isinstance(base, dict):
            return str(base.get("ref", ""))
    wf_run = payload.get("workflow_run")
    if isinstance(wf_run, dict):
        return str(wf_run.get("head_branch", ""))
    return ""


def bootstrap_builtin_destinations(registry: DestinationRegistry | None = None) -> DestinationRegistry:
    """Register built-in destinations and return a ready registry."""
    target = registry or DestinationRegistry()

    target.register("telegram", lambda **kwargs: TelegramDestination())

    def _discord_factory(**kwargs) -> Destination | None:
        url = settings.discord_webhook_url
        if not url:
            logger.warning("Route references 'discord' but DISCORD_WEBHOOK_URL is not set")
            return None
        return DiscordDestination(url, http_client=kwargs.get("http_client"))

    def _slack_factory(**kwargs) -> Destination | None:
        url = settings.slack_webhook_url
        if not url:
            logger.warning("Route references 'slack' but SLACK_WEBHOOK_URL is not set")
            return None
        return SlackDestination(url, http_client=kwargs.get("http_client"))

    target.register("discord", _discord_factory)  # type: ignore[arg-type]
    target.register("slack", _slack_factory)  # type: ignore[arg-type]
    return target


_DESTINATION_REGISTRY = bootstrap_builtin_destinations()


def register_destination(name: str, factory: Any) -> None:
    """Register a custom/plugin destination factory in the global registry."""
    _DESTINATION_REGISTRY.register(name, factory)


def destination_health_snapshot() -> dict[str, Any]:
    """Routing destination snapshot for deep health checks."""
    registered = _DESTINATION_REGISTRY.list_registered()
    active: list[str] = []

    for name in registered:
        if not _is_destination_enabled(name):
            continue
        if name == "discord" and not settings.discord_webhook_url:
            continue
        if name == "slack" and not settings.slack_webhook_url:
            continue
        active.append(name)

    return {
        "registered": registered,
        "active": active,
        "fallback_safe": True,
    }


def _build_destination(name: str, http_client: httpx.AsyncClient | None = None) -> Destination | None:
    """Instantiate a destination by name via registry lookup."""
    if not _is_destination_enabled(name):
        logger.info("Destination %r disabled by feature flag", name)
        return None

    factory = _DESTINATION_REGISTRY.get(name)
    if factory is None:
        logger.warning("Unknown destination %r in route config", name)
        return None
    return factory(http_client=http_client)


def load_routes(yaml_source: str | None = None) -> list[Route]:
    """Parse YAML route config and return a list of Route objects.

    *yaml_source* can be:
    - A filesystem path to a ``.yaml`` / ``.yml`` file
    - An inline YAML string
    - ``None`` → fall back to ``settings.routes_yaml``

    Returns an empty list if no routing config is provided (the caller
    should fall back to the default Telegram-only behaviour).
    """
    raw = yaml_source or settings.routes_yaml
    if not raw:
        return []

    # If it looks like a file path, try reading it
    if not raw.lstrip().startswith("{") and not raw.lstrip().startswith("routes"):
        expanded = os.path.expanduser(raw)
        if os.path.isfile(expanded):
            with open(expanded) as fh:
                raw = fh.read()

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        logger.error("Failed to parse routes YAML")
        return []

    if not isinstance(data, dict):
        return []

    routes_list = data.get("routes", [])
    if not isinstance(routes_list, list):
        return []

    routes: list[Route] = []
    for entry in routes_list:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", f"route-{len(routes)}"))
        dest = str(entry.get("destination", "telegram"))
        filt_raw = entry.get("filter", {})
        filt = RouteFilter(
            event_type=filt_raw.get("event_type") if isinstance(filt_raw, dict) else None,
            repo=filt_raw.get("repo") if isinstance(filt_raw, dict) else None,
            branch=filt_raw.get("branch") if isinstance(filt_raw, dict) else None,
        )
        routes.append(Route(name=name, destination_name=dest, filter=filt))

    logger.info("Loaded %d route(s) from config", len(routes))
    return routes


async def route_event(
    routes: list[Route],
    message: str,
    event_type: str,
    payload: dict[str, Any],
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Evaluate all routes and deliver *message* to matching destinations.

    Returns a list of ``{"destination": ..., "status": "sent"|"failed", ...}``
    dicts for observability.
    """
    results: list[dict[str, Any]] = []

    for route in routes:
        if not route.filter.matches(event_type, payload):
            continue

        dest = _build_destination(route.destination_name, http_client=http_client)
        if dest is None:
            results.append({"route": route.name, "destination": route.destination_name, "status": "skipped"})
            continue

        try:
            await dest.send(message, event_type=event_type, payload=payload)
            results.append({"route": route.name, "destination": dest.name, "status": "sent"})
        except DestinationError as exc:
            logger.error("Route %r delivery to %s failed: %s", route.name, dest.name, exc)
            result: dict[str, Any] = {
                "route": route.name,
                "destination": dest.name,
                "status": "failed",
                "error": str(exc),
                "error_classification": exc.classification,
                "retryable": exc.retryable,
            }
            if exc.status_code is not None:
                result["status_code"] = exc.status_code
            if exc.retry_after_seconds is not None:
                result["retry_after_seconds"] = exc.retry_after_seconds
            results.append(result)

    return results
