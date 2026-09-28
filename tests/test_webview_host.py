"""Tests for the desktop host bridge without opening a native window."""

from types import SimpleNamespace
from typing import cast

import pytest

from app.webview_host import AsyncioBackendHost, WebUIBridge, resolve_frontend_url


def test_bridge_reads_shared_runtime_status() -> None:
    runtime_state = SimpleNamespace(status=lambda: (True, 42), twitch_connected=True)
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(twitch_channel="channel", twitch_bot_username="bot"),
    )
    backend = SimpleNamespace(application=application)

    result = WebUIBridge(cast(AsyncioBackendHost, backend)).get_app_status()

    assert result == {
        "running": True,
        "twitch_connected": True,
        "uptime_seconds": 42,
        "channel": "channel",
        "account": "bot",
    }


def test_bridge_gets_commands_from_registry_and_effective_runtime_settings() -> None:
    definition = SimpleNamespace(
        name="erase",
        aliases=("forget",),
        hidden=True,
    )
    settings = SimpleNamespace(
        enabled=False,
        permission=SimpleNamespace(name="BROADCASTER"),
        cooldown=SimpleNamespace(per_user_seconds=3.0, global_seconds=5.0),
    )
    runtime_state = SimpleNamespace(get_command_settings=lambda name: settings)
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        registry=SimpleNamespace(definitions=lambda: (definition,)),
        settings=SimpleNamespace(command_prefix="!"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))

    result = bridge.get_commands()

    assert result == {
        "command_prefix": "!",
        "commands": [
            {
                "name": "erase",
                "aliases": ["forget"],
                "enabled": False,
                "permission": "BROADCASTER",
                "cooldown": {
                    "per_user_seconds": 3.0,
                    "global_seconds": 5.0,
                },
                "hidden": True,
            }
        ],
    }


def test_bridge_gets_ai_state_without_exposing_personality_prompts() -> None:
    runtime_state = SimpleNamespace(
        ai_enabled=True,
        ai_memory_enabled=False,
        active_ai_personality="neutral",
        available_personalities=("neutral", "vas"),
    )
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(gemini_model="gemini-test"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))

    assert bridge.get_ai_status() == {
        "enabled": True,
        "memory_enabled": False,
        "active_personality": "neutral",
        "available_personalities": ["neutral", "vas"],
        "model": "gemini-test",
    }


def test_production_frontend_requires_a_built_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.webview_host.FRONTEND_ENTRYPOINT",
        SimpleNamespace(is_file=lambda: False),
    )

    with pytest.raises(FileNotFoundError, match="npm run build"):
        resolve_frontend_url(None)


def test_development_frontend_url_does_not_require_build() -> None:
    assert resolve_frontend_url("http://localhost:5173") == "http://localhost:5173"
