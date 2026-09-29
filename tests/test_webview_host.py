"""Tests for the desktop host bridge without opening a native window."""

import asyncio
import logging
from concurrent.futures import Future
from types import SimpleNamespace
from typing import cast

import pytest

from app.commands.registry import CommandRegistry
from app.app_settings import AISettings, AppSettings, AppSettingsStore, TwitchSettings
from app.config.settings import Settings
from app.credentials import CredentialStatus
from app.runtime_state import RuntimeState
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.utils.logging import RecentLogBuffer, RecentLogHandler
from app.webview_host import (
    AsyncioBackendHost,
    DesktopController,
    WebUIBridge,
    apply_ai_app_settings,
    apply_twitch_app_settings,
    resolve_frontend_url,
)


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


def test_twitch_app_settings_override_environment_defaults() -> None:
    settings = Settings(
        _env_file=None,
        twitch_client_id="client-id",
        twitch_client_secret="client-secret",
        twitch_bot_user_id="100",
        twitch_bot_username="testbot",
        twitch_channel_user_id="200",
        twitch_channel="environment-channel",
    )

    effective = apply_twitch_app_settings(
        settings,
        AppSettings(
            twitch=TwitchSettings(
                channel="local-channel",
                channel_user_id="300",
            )
        ),
    )

    assert effective.twitch_channel == "local-channel"
    assert effective.twitch_channel_user_id == "300"
    assert settings.twitch_channel == "environment-channel"


def test_ai_app_settings_override_environment_model_defaults() -> None:
    settings = Settings(
        _env_file=None,
        twitch_client_id="client-id",
        twitch_client_secret="client-secret",
        twitch_bot_user_id="100",
        twitch_bot_username="testbot",
        twitch_channel_user_id="200",
        twitch_channel="channel",
        gemini_model="gemini-environment",
        gemini_fallback_model="gemini-environment-fallback",
    )

    effective = apply_ai_app_settings(
        settings,
        AppSettings(
            ai=AISettings(
                selected_model="gemini-local",
                fallback_model="gemini-local-fallback",
            )
        ),
    )

    assert effective.gemini_model == "gemini-local"
    assert effective.gemini_fallback_model == "gemini-local-fallback"
    assert settings.gemini_model == "gemini-environment"


def test_bridge_exposes_and_updates_ai_provider_settings(tmp_path) -> None:
    settings = SimpleNamespace(
        gemini_model="gemini-selected",
        gemini_fallback_model="gemini-fallback",
    )
    application = SimpleNamespace(
        settings=settings,
        services=SimpleNamespace(ai=SimpleNamespace()),
    )
    credential_manager = SimpleNamespace(
        statuses=lambda: (
            CredentialStatus(
                name="gemini_api_key",
                label="Gemini API key",
                configured=True,
                source="environment",
                secure_storage_available=True,
            ),
        )
    )
    store = AppSettingsStore(tmp_path / "app_settings.json")
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace(application=application)),
        app_settings=store,
        credential_manager=credential_manager,
    )

    result = bridge.get_ai_provider_settings()
    assert result["ok"] is True
    assert result["settings"]["provider"] == "Google Gemini"
    assert result["settings"]["selected_model"] == "gemini-selected"
    assert result["settings"]["credential"]["configured"] is True
    assert "value" not in result["settings"]["credential"]

    assert bridge.update_ai_provider_settings("gemini-new", "gemini-safe") == {
        "ok": True
    }
    assert settings.gemini_model == "gemini-new"
    assert settings.gemini_fallback_model == "gemini-safe"
    assert store.snapshot().ai == AISettings(
        selected_model="gemini-new",
        fallback_model="gemini-safe",
    )


def test_bridge_discovers_models_on_the_existing_backend_loop() -> None:
    class FakeAI:
        async def discover_models(self) -> list[str]:
            return ["gemini-discovered"]

    class FakeBackend:
        application = SimpleNamespace(services=SimpleNamespace(ai=FakeAI()))

        def submit(self, coroutine):
            future: Future[list[str]] = Future()
            future.set_result(asyncio.run(coroutine))
            return future

    bridge = WebUIBridge(cast(AsyncioBackendHost, FakeBackend()))

    assert bridge.discover_gemini_models() == {
        "ok": True,
        "models": ["gemini-discovered"],
    }


def test_bridge_exposes_and_saves_non_secret_twitch_settings(tmp_path) -> None:
    token_path = tmp_path / "tokens.json"
    token_path.write_text("{}", encoding="utf-8")
    runtime_state = SimpleNamespace(
        status=lambda: (True, 12),
        twitch_connected=True,
    )
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(
            twitch_channel="environment-channel",
            twitch_channel_user_id="200",
            twitch_bot_username="testbot",
            twitch_bot_user_id="100",
            twitch_token_file=str(token_path),
        ),
    )
    store = AppSettingsStore(tmp_path / "app_settings.json")
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace(application=application)),
        app_settings=store,
    )

    initial = bridge.get_twitch_settings()
    assert initial["settings"] == {
        "target_channel": "environment-channel",
        "target_channel_user_id": "200",
        "active_channel": "environment-channel",
        "bot_username": "testbot",
        "bot_user_id": "100",
        "running": True,
        "connected": True,
        "oauth_token_available": True,
        "has_local_override": False,
    }
    assert bridge.update_twitch_settings("NewChannel", "300") == {
        "ok": True,
        "requires_reconnect": True,
    }
    assert store.snapshot().twitch == TwitchSettings(
        channel="newchannel",
        channel_user_id="300",
    )


def test_bridge_reconnects_through_existing_bot_runtime(tmp_path) -> None:
    calls: list[tuple[str, str]] = []

    class FakeBotRuntime:
        async def reconnect_twitch(self, *, channel: str, channel_user_id: str) -> bool:
            calls.append((channel, channel_user_id))
            return True

    class FakeBackend:
        def __init__(self) -> None:
            self.application = SimpleNamespace(
                services=SimpleNamespace(
                    runtime_state=SimpleNamespace(
                        status=lambda: (True, 1),
                        twitch_connected=True,
                    )
                ),
                settings=SimpleNamespace(
                    twitch_channel="oldchannel",
                    twitch_channel_user_id="200",
                ),
            )
            self.bot_runtime = FakeBotRuntime()

        def submit(self, coroutine):
            future: Future[bool] = Future()
            future.set_result(asyncio.run(coroutine))
            return future

    store = AppSettingsStore(tmp_path / "app_settings.json")
    store.update_twitch(channel="newchannel", channel_user_id="300")
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, FakeBackend()),
        app_settings=store,
    )

    assert bridge.reconnect_twitch() == {"ok": True, "changed": True}
    assert calls == [("newchannel", "300")]


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
    runtime_state = SimpleNamespace(
        get_command_settings=lambda name: settings,
        get_command_default_settings=lambda name: settings,
        command_settings_are_saved=lambda name: True,
        has_saved_command_override=lambda name: False,
    )
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        registry=SimpleNamespace(definitions=lambda: (definition,)),
        settings=SimpleNamespace(command_prefix="!"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))

    result = bridge.get_commands()

    assert result == {
        "command_prefix": "!",
        "permissions": [
            "USER",
            "SUBSCRIBER",
            "VIP",
            "MODERATOR",
            "BROADCASTER",
        ],
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
                "default_settings": {
                    "enabled": False,
                    "permission": "BROADCASTER",
                    "cooldown": {
                        "per_user_seconds": 3.0,
                        "global_seconds": 5.0,
                    },
                },
                "saved": True,
                "has_saved_override": False,
            }
        ],
    }


def build_command_bridge(tmp_path) -> tuple[WebUIBridge, RuntimeState]:
    registry = CommandRegistry()

    @registry.command(
        "ping",
        required_permission=Permission.MODERATOR,
        cooldown=CooldownPolicy(global_seconds=10.0),
    )
    async def ping(context, arguments: str) -> None:
        return None

    runtime_state = RuntimeState(command_settings_path=tmp_path / "command_settings.json")
    runtime_state.configure_commands(registry.definitions())
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        registry=registry,
        settings=SimpleNamespace(command_prefix="!"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))
    return bridge, runtime_state


def test_bridge_applies_command_settings_for_current_runtime(tmp_path) -> None:
    bridge, runtime_state = build_command_bridge(tmp_path)

    result = bridge.apply_command_settings("ping", False, 2, 3.5, "VIP")

    assert result == {"ok": True}
    settings = runtime_state.get_command_settings("ping")
    assert settings.enabled is False
    assert settings.cooldown == CooldownPolicy(2.0, 3.5)
    assert settings.permission is Permission.VIP
    assert runtime_state.command_settings_are_saved("ping") is False


@pytest.mark.parametrize(
    ("enabled", "per_user", "global_value", "permission", "expected_error"),
    [
        ("false", 0, 0, "USER", "Enabled must be a boolean."),
        (True, -1, 0, "USER", "Cooldown values must be non-negative numbers."),
        (True, float("nan"), 0, "USER", "Cooldown values must be non-negative numbers."),
        (True, 0, 0, "OWNER", "Permission must be a valid permission name."),
    ],
)
def test_bridge_rejects_invalid_command_settings(
    tmp_path,
    enabled,
    per_user,
    global_value,
    permission,
    expected_error: str,
) -> None:
    bridge, runtime_state = build_command_bridge(tmp_path)
    original = runtime_state.get_command_settings("ping")

    result = bridge.apply_command_settings(
        "ping",
        enabled,
        per_user,
        global_value,
        permission,
    )

    assert result == {"ok": False, "error": expected_error}
    assert runtime_state.get_command_settings("ping") == original


def test_bridge_saves_and_resets_command_settings(tmp_path) -> None:
    bridge, runtime_state = build_command_bridge(tmp_path)

    assert bridge.save_command_settings("ping", False, 1, 2, "BROADCASTER") == {
        "ok": True
    }
    assert runtime_state.has_saved_command_override("ping") is True
    assert bridge.reset_command_settings("ping") == {"ok": True}
    assert runtime_state.get_command_settings("ping").permission is Permission.MODERATOR
    assert runtime_state.has_saved_command_override("ping") is False


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


def build_ai_bridge(tmp_path) -> tuple[WebUIBridge, RuntimeState]:
    registry = CommandRegistry()

    @registry.command("ask")
    async def ask(context, arguments: str) -> None:
        return None

    runtime_state = RuntimeState(
        command_settings_path=tmp_path / "command_settings.json",
        personality_settings_path=tmp_path / "personality_settings.json",
    )
    runtime_state.configure_commands(registry.definitions())
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        registry=registry,
        settings=SimpleNamespace(gemini_model="gemini-test"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))
    return bridge, runtime_state


def test_bridge_exposes_only_personality_specific_editable_prompts(tmp_path) -> None:
    bridge, runtime_state = build_ai_bridge(tmp_path)

    result = bridge.get_personalities()

    assert result["active_personality"] == runtime_state.active_ai_personality
    neutral = next(
        item for item in result["personalities"] if item["name"] == "neutral"
    )
    assert "You are a Twitch chat assistant." not in neutral["prompt"]
    assert neutral["prompt"] == neutral["built_in_prompt"]


def test_bridge_applies_saves_and_resets_personality(tmp_path) -> None:
    bridge, runtime_state = build_ai_bridge(tmp_path)

    assert bridge.apply_personality("neutral", "temporary") == {"ok": True}
    assert runtime_state.get_ai_personality_prompt("neutral") == "temporary"
    assert runtime_state.active_ai_personality_is_saved is False

    assert bridge.save_personality("neutral", "saved") == {"ok": True}
    assert runtime_state.get_ai_personality_prompt("neutral") == "saved"
    assert runtime_state.has_saved_personality_override("neutral") is True

    assert bridge.reset_personality("neutral") == {"ok": True}
    assert runtime_state.has_saved_personality_override("neutral") is False
    assert runtime_state.get_ai_personality_prompt("neutral") == (
        runtime_state.get_builtin_ai_personality_prompt("neutral")
    )


def test_bridge_updates_ai_runtime_toggles_with_validation(tmp_path) -> None:
    bridge, runtime_state = build_ai_bridge(tmp_path)

    assert bridge.set_ai_enabled(False) == {"ok": True}
    assert runtime_state.ai_enabled is False
    assert bridge.set_ai_memory_enabled(False) == {"ok": True}
    assert runtime_state.ai_memory_enabled is False
    assert bridge.set_ai_enabled("false") == {
        "ok": False,
        "error": "Enabled must be a boolean.",
    }


def test_bridge_reads_bounded_logs_with_validated_cursor_arguments() -> None:
    log_buffer = RecentLogBuffer(max_entries=2)
    handler = RecentLogHandler(log_buffer)
    for message in ("first", "second", "third"):
        handler.emit(
            logging.LogRecord(
                name="tests.webview",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg=message,
                args=(),
                exc_info=None,
            )
        )
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace()),
        log_buffer=log_buffer,
    )

    result = bridge.get_recent_logs(after_id=2, limit=5000)

    assert [entry["message"] for entry in result["entries"]] == ["third"]


def test_production_frontend_requires_a_built_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.webview_host.FRONTEND_ENTRYPOINT",
        SimpleNamespace(is_file=lambda: False),
    )

    with pytest.raises(FileNotFoundError, match="npm run build"):
        resolve_frontend_url(None)


def test_development_frontend_url_does_not_require_build() -> None:
    assert resolve_frontend_url("http://localhost:5173") == "http://localhost:5173"


class FakeEvent:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self) -> None:
        self.events = SimpleNamespace(
            closing=FakeEvent(),
            closed=FakeEvent(),
            minimized=FakeEvent(),
        )
        self.hide_calls = 0
        self.show_calls = 0
        self.restore_calls = 0
        self.destroy_calls = 0

    def hide(self) -> None:
        self.hide_calls += 1

    def show(self) -> None:
        self.show_calls += 1

    def restore(self) -> None:
        self.restore_calls += 1

    def destroy(self) -> None:
        self.destroy_calls += 1


class FakeTray:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.update_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def update_menu(self) -> None:
        self.update_calls += 1


class FakeDesktopRuntimeState:
    def __init__(self) -> None:
        self.running = False

    def status(self) -> tuple[bool, int]:
        return self.running, 0


class FakeDesktopBackend:
    def __init__(self) -> None:
        self.runtime_state = FakeDesktopRuntimeState()
        self.application = SimpleNamespace(
            services=SimpleNamespace(runtime_state=self.runtime_state)
        )
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeDesktopBridge:
    def __init__(self, runtime_state: FakeDesktopRuntimeState) -> None:
        self.runtime_state = runtime_state
        self.start_calls = 0
        self.stop_calls = 0

    def start_bot(self) -> dict[str, object]:
        self.start_calls += 1
        self.runtime_state.running = True
        return {"ok": True}

    def stop_bot(self) -> dict[str, object]:
        self.stop_calls += 1
        self.runtime_state.running = False
        return {"ok": True}


def build_desktop_controller(tmp_path):
    backend = FakeDesktopBackend()
    bridge = FakeDesktopBridge(backend.runtime_state)
    tray = FakeTray()
    store = AppSettingsStore(tmp_path / "app_settings.json")
    controller = DesktopController(
        cast(AsyncioBackendHost, backend),
        cast(WebUIBridge, bridge),
        store,
        tray=tray,
    )
    window = FakeWindow()
    controller.bind_window(window)
    return controller, backend, bridge, tray, store, window


def test_desktop_controller_hides_window_for_saved_tray_settings(tmp_path) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )
    store.update_window(
        start_minimized=True,
        minimize_to_tray=True,
        close_to_tray=True,
    )

    controller.start_tray()
    controller.start_tray()
    assert window.events.closing.handlers[0]() is False
    window.events.minimized.handlers[0]()
    controller.open_window()

    assert tray.start_calls == 1
    assert window.hide_calls == 2
    assert window.show_calls == 1
    assert window.restore_calls == 1
    assert backend.close_calls == 0


def test_desktop_controller_tray_toggles_bot_and_exits_orderly(tmp_path) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )

    controller.toggle_bot()
    controller.toggle_bot()
    controller.exit_application()
    controller.exit_application()
    controller.shutdown()

    assert bridge.start_calls == 1
    assert bridge.stop_calls == 1
    assert tray.update_calls == 2
    assert backend.close_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1


def test_desktop_controller_allows_normal_close_when_setting_is_disabled(
    tmp_path,
) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )

    assert window.events.closing.handlers[0]() is None
    assert window.hide_calls == 0
    window.events.closed.handlers[0]()

    assert backend.close_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 0


def test_desktop_controller_allows_normal_minimize_when_setting_is_disabled(
    tmp_path,
) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )

    window.events.minimized.handlers[0]()

    assert window.hide_calls == 0
    assert backend.close_calls == 0
