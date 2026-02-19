"""Tests for the routing engine."""

import pytest

from app.services.routing import (
    _DESTINATION_REGISTRY,
    Route,
    RouteFilter,
    _build_destination,
    _extract_branch,
    bootstrap_builtin_destinations,
    destination_health_snapshot,
    load_routes,
    route_event,
)
from destinations.base import Destination, DestinationError

# ---------------------------------------------------------------------------
# RouteFilter.matches
# ---------------------------------------------------------------------------


class TestRouteFilter:
    def test_empty_filter_matches_everything(self):
        f = RouteFilter()
        assert f.matches("push", {"repository": {"full_name": "a/b"}})
        assert f.matches("issues", {})

    def test_event_type_match(self):
        f = RouteFilter(event_type="push")
        assert f.matches("push", {})
        assert not f.matches("issues", {})

    def test_repo_match(self):
        f = RouteFilter(repo="octocat/Hello-World")
        payload = {"repository": {"full_name": "octocat/Hello-World"}}
        assert f.matches("push", payload)
        assert not f.matches("push", {"repository": {"full_name": "other/repo"}})
        assert not f.matches("push", {})

    def test_branch_match_push(self):
        f = RouteFilter(branch="main")
        assert f.matches("push", {"ref": "refs/heads/main"})
        assert not f.matches("push", {"ref": "refs/heads/develop"})

    def test_branch_match_pr(self):
        f = RouteFilter(branch="main")
        payload = {"pull_request": {"base": {"ref": "main"}}}
        assert f.matches("pull_request", payload)

    def test_branch_match_workflow_run(self):
        f = RouteFilter(branch="main")
        payload = {"workflow_run": {"head_branch": "main"}}
        assert f.matches("workflow_run", payload)

    def test_combined_filters_all_must_match(self):
        f = RouteFilter(event_type="push", repo="a/b", branch="main")
        payload = {"repository": {"full_name": "a/b"}, "ref": "refs/heads/main"}
        assert f.matches("push", payload)
        # Wrong event type
        assert not f.matches("issues", payload)
        # Wrong branch
        payload_dev = {"repository": {"full_name": "a/b"}, "ref": "refs/heads/develop"}
        assert not f.matches("push", payload_dev)


# ---------------------------------------------------------------------------
# _extract_branch
# ---------------------------------------------------------------------------


class TestExtractBranch:
    def test_push(self):
        assert _extract_branch("push", {"ref": "refs/heads/main"}) == "main"

    def test_pr(self):
        assert _extract_branch("pull_request", {"pull_request": {"base": {"ref": "develop"}}}) == "develop"

    def test_workflow_run(self):
        assert _extract_branch("workflow_run", {"workflow_run": {"head_branch": "feat"}}) == "feat"

    def test_unknown_event(self):
        assert _extract_branch("issues", {}) == ""


# ---------------------------------------------------------------------------
# load_routes
# ---------------------------------------------------------------------------


class TestLoadRoutes:
    def test_empty_string_returns_empty(self):
        assert load_routes("") == []

    def test_none_returns_empty(self):
        assert load_routes("") == []

    def test_inline_yaml(self):
        yaml_str = """
routes:
  - name: test-route
    destination: telegram
    filter:
      event_type: push
"""
        routes = load_routes(yaml_str)
        assert len(routes) == 1
        assert routes[0].name == "test-route"
        assert routes[0].destination_name == "telegram"
        assert routes[0].filter.event_type == "push"

    def test_file_path(self, tmp_path):
        cfg = tmp_path / "routes.yaml"
        cfg.write_text("""
routes:
  - name: from-file
    destination: discord
""")
        routes = load_routes(str(cfg))
        assert len(routes) == 1
        assert routes[0].name == "from-file"

    def test_invalid_yaml_returns_empty(self):
        assert load_routes("{{{{invalid") == []

    def test_no_routes_key_returns_empty(self):
        assert load_routes("foo: bar") == []

    def test_multiple_routes(self):
        yaml_str = """
routes:
  - name: r1
    destination: telegram
  - name: r2
    destination: discord
    filter:
      event_type: release
  - name: r3
    destination: slack
    filter:
      branch: main
      repo: a/b
"""
        routes = load_routes(yaml_str)
        assert len(routes) == 3
        assert routes[1].filter.event_type == "release"
        assert routes[2].filter.branch == "main"
        assert routes[2].filter.repo == "a/b"

    def test_default_destination_is_telegram(self):
        routes = load_routes("routes:\n  - name: x\n")
        assert routes[0].destination_name == "telegram"


# ---------------------------------------------------------------------------
# route_event
# ---------------------------------------------------------------------------


class TestDestinationBootstrap:
    def test_builtin_destinations_registered(self):
        registry = bootstrap_builtin_destinations()

        assert registry.get("telegram") is not None
        assert registry.get("discord") is not None
        assert registry.get("slack") is not None

    def test_build_destination_uses_registry_lookup(self, monkeypatch):
        calls = []

        def factory(**kwargs):
            calls.append(kwargs)
            return FakeDestination("from-registry")

        monkeypatch.setattr(_DESTINATION_REGISTRY, "get", lambda name: factory if name == "x" else None)

        dest = _build_destination("x")

        assert isinstance(dest, FakeDestination)
        assert dest.name == "from-registry"
        assert calls == [{"http_client": None}]

    def test_destination_feature_flag_disables_destination(self, monkeypatch):
        monkeypatch.setattr("app.services.routing.settings.destination_feature_flags", "telegram=false")

        assert _build_destination("telegram") is None

    def test_destination_health_snapshot(self, monkeypatch):
        monkeypatch.setattr("app.services.routing.settings.destination_feature_flags", "slack=false")
        monkeypatch.setattr("app.services.routing.settings.discord_webhook_url", "")

        snap = destination_health_snapshot()

        assert "telegram" in snap["registered"]
        assert "telegram" in snap["active"]
        assert "slack" not in snap["active"]
        assert snap["fallback_safe"] is True


class FakeDestination(Destination):
    def __init__(self, name_val: str = "fake", should_fail: bool = False):
        self._name = name_val
        self._should_fail = should_fail
        self.sent_messages: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    async def send(self, message, *, event_type, payload):
        if self._should_fail:
            raise DestinationError(self._name, "boom")
        self.sent_messages.append(message)


class TestRouteEvent:
    @pytest.mark.asyncio
    async def test_matching_telegram_route_sends(self, monkeypatch):
        dest = FakeDestination("telegram")
        monkeypatch.setattr("app.services.routing._build_destination", lambda name, **kwargs: dest)

        routes = [Route(name="all", destination_name="telegram")]
        results = await route_event(routes, "hello", "push", {})
        assert len(results) == 1
        assert results[0] == {"route": "all", "destination": "telegram", "status": "sent"}
        assert dest.sent_messages == ["hello"]

    @pytest.mark.asyncio
    async def test_non_matching_route_skipped(self, monkeypatch):
        dest = FakeDestination("telegram")
        monkeypatch.setattr("app.services.routing._build_destination", lambda name, **kwargs: dest)

        routes = [Route(name="releases", destination_name="telegram", filter=RouteFilter(event_type="release"))]
        results = await route_event(routes, "hello", "push", {})
        assert results == []
        assert dest.sent_messages == []

    @pytest.mark.asyncio
    async def test_failed_destination(self, monkeypatch):
        dest = FakeDestination("discord", should_fail=True)
        monkeypatch.setattr("app.services.routing._build_destination", lambda name, **kwargs: dest)

        routes = [Route(name="r", destination_name="discord")]
        results = await route_event(routes, "hello", "push", {})
        assert results[0]["status"] == "failed"
        assert "error" in results[0]

    @pytest.mark.asyncio
    async def test_none_destination_skipped(self, monkeypatch):
        monkeypatch.setattr("app.services.routing._build_destination", lambda name, **kwargs: None)

        routes = [Route(name="r", destination_name="unknown")]
        results = await route_event(routes, "hello", "push", {})
        assert results[0] == {"route": "r", "destination": "unknown", "status": "skipped"}

    @pytest.mark.asyncio
    async def test_unknown_destination_skipped_and_warning_logged(self, caplog):
        routes = [Route(name="unknown-route", destination_name="not-a-provider")]

        with caplog.at_level("WARNING"):
            results = await route_event(routes, "hello", "push", {})

        assert results == [{"route": "unknown-route", "destination": "not-a-provider", "status": "skipped"}]
        assert "Unknown destination" in caplog.text

    @pytest.mark.asyncio
    async def test_multiple_routes_multiple_destinations(self, monkeypatch):
        dest_tg = FakeDestination("telegram")
        dest_dc = FakeDestination("discord")

        def build(name, **kwargs):
            return dest_tg if name == "telegram" else dest_dc

        monkeypatch.setattr("app.services.routing._build_destination", build)

        routes = [
            Route(name="tg", destination_name="telegram"),
            Route(name="dc", destination_name="discord", filter=RouteFilter(event_type="push")),
        ]
        results = await route_event(routes, "msg", "push", {})
        assert len(results) == 2
        assert all(r["status"] == "sent" for r in results)

    @pytest.mark.asyncio
    async def test_mixed_routes_continue_when_one_destination_fails(self, monkeypatch):
        dest_tg = FakeDestination("telegram")
        dest_dc = FakeDestination("discord", should_fail=True)

        def build(name, **kwargs):
            return dest_tg if name == "telegram" else dest_dc

        monkeypatch.setattr("app.services.routing._build_destination", build)

        routes = [
            Route(name="dc", destination_name="discord"),
            Route(name="tg", destination_name="telegram"),
        ]

        results = await route_event(routes, "msg", "push", {})

        assert results[0]["status"] == "failed"
        assert results[1] == {"route": "tg", "destination": "telegram", "status": "sent"}
        assert dest_tg.sent_messages == ["msg"]

    @pytest.mark.asyncio
    async def test_route_event_output_shape_contract(self, monkeypatch):
        sent = FakeDestination("telegram")
        failed = FakeDestination("discord", should_fail=True)

        def build(name, **kwargs):
            if name == "telegram":
                return sent
            if name == "discord":
                return failed
            return None

        monkeypatch.setattr("app.services.routing._build_destination", build)

        routes = [
            Route(name="s", destination_name="telegram"),
            Route(name="f", destination_name="discord"),
            Route(name="k", destination_name="unknown"),
        ]
        results = await route_event(routes, "msg", "push", {})

        assert results[0] == {"route": "s", "destination": "telegram", "status": "sent"}
        assert set(results[1].keys()) == {"route", "destination", "status", "error"}
        assert results[1]["route"] == "f"
        assert results[1]["destination"] == "discord"
        assert results[1]["status"] == "failed"
        assert isinstance(results[1]["error"], str)
        assert results[2] == {"route": "k", "destination": "unknown", "status": "skipped"}
