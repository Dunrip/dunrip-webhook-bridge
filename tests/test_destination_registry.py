"""Tests for destination registry foundation API."""

import pytest

from destinations import DestinationRegistry
from destinations.base import Destination


class DummyDestination(Destination):
    @property
    def name(self) -> str:
        return "dummy"

    async def send(self, message: str, *, event_type: str, payload: dict):
        return None


def dummy_factory(**kwargs) -> Destination:
    return DummyDestination()


def test_register_and_get_factory():
    registry = DestinationRegistry()

    registry.register("telegram", dummy_factory)

    factory = registry.get("telegram")
    assert factory is dummy_factory


def test_get_missing_returns_none():
    registry = DestinationRegistry()

    assert registry.get("missing") is None


def test_list_registered_sorted():
    registry = DestinationRegistry()

    registry.register("slack", dummy_factory)
    registry.register("telegram", dummy_factory)

    assert registry.list_registered() == ["slack", "telegram"]


def test_duplicate_registration_rejected():
    registry = DestinationRegistry()

    registry.register("discord", dummy_factory)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("discord", dummy_factory)


def test_registration_normalizes_name():
    registry = DestinationRegistry()

    registry.register("  TeLeGrAm  ", dummy_factory)

    assert registry.get("telegram") is dummy_factory


def test_register_requires_non_empty_name():
    registry = DestinationRegistry()

    with pytest.raises(ValueError, match="non-empty"):
        registry.register("   ", dummy_factory)
