"""Tests for command registration."""

import pytest

from app.commands.registry import CommandRegistry


def test_registry_registers_normalized_name_and_alias() -> None:
    registry = CommandRegistry()

    @registry.command("Ping", aliases=("P",))
    async def ping(context, arguments: str) -> None:
        return None

    assert registry.get("ping") is registry.get("P")
    assert registry.names() == ("ping",)


def test_registry_rejects_duplicate_names() -> None:
    registry = CommandRegistry()

    @registry.command("ping")
    async def ping(context, arguments: str) -> None:
        return None

    with pytest.raises(ValueError):
        @registry.command("PING")
        async def duplicate_ping(context, arguments: str) -> None:
            return None