"""Focused tests for local desktop application settings."""

import asyncio
import json
import logging
import sys
from concurrent.futures import Future
from types import SimpleNamespace
from typing import cast

import pytest

from app.app_settings import (
    APP_SETTINGS_VERSION,
    AISettings,
    AppSettings,
    AppSettingsStore,
    StartupSettings,
    TwitchConnectionPreset,
    TwitchSettings,
    WindowSettings,
    load_app_settings,
)
from app.webview_host import AsyncioBackendHost, WebUIBridge
from app.config_file import ConfigFile
from config_helpers import read_section, write_section


def complete_bridge_coroutine(coroutine) -> Future:
    future: Future = Future()
    try:
        future.set_result(asyncio.run(coroutine))
    except BaseException as error:
        future.set_exception(error)
    return future


def test_missing_app_settings_file_uses_safe_defaults(tmp_path) -> None:
    settings = load_app_settings(ConfigFile(tmp_path / "app_settings.json").section("app"))

    assert settings == AppSettings()


def test_partial_and_invalid_app_settings_fall_back_individually(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings_path = tmp_path / "app_settings.json"
    write_section(settings_path, "app", {
                "version": APP_SETTINGS_VERSION,
                "window": {
                    "start_minimized": True,
                    "minimize_to_tray": "yes",
                    "close_to_tray": False,
                },
                "startup": {"auto_start_bot": "yes"},
                "ai": {"memory_enabled": "yes"},
            })

    with caplog.at_level(logging.WARNING):
        settings = load_app_settings(ConfigFile(settings_path).section("app"))

    assert settings == AppSettings(window=WindowSettings(start_minimized=True))
    assert "invalid application setting" in caplog.text


@pytest.mark.parametrize("file_content", ["", "[]", "{not-json"])
def test_malformed_app_settings_file_does_not_block_startup(
    tmp_path,
    file_content: str,
) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(file_content, encoding="utf-8")

    assert load_app_settings(ConfigFile(settings_path).section("app")) == AppSettings(startup=StartupSettings(operation_mode="disabled"))


def test_unknown_app_settings_version_uses_defaults(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    write_section(settings_path, "app", {"version": 99, "window": {"start_minimized": True}})

    assert load_app_settings(ConfigFile(settings_path).section("app")) == AppSettings(startup=StartupSettings(operation_mode="disabled"))


def test_app_settings_store_saves_atomically_and_reloads(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    store = AppSettingsStore(ConfigFile(settings_path))

    store.update_ai_memory(enabled=False)
    updated = store.update_desktop(
        start_minimized=True,
        minimize_to_tray=True,
        close_to_tray=False,
        auto_start_bot=True,
    )

    assert updated == AppSettings(
        window=WindowSettings(start_minimized=True, minimize_to_tray=True),
        startup=StartupSettings(auto_start_bot=True),
        ai=AISettings(memory_enabled=False),
    )
    assert AppSettingsStore(ConfigFile(settings_path)).snapshot() == updated
    assert read_section(settings_path, "app") == {
        "version": APP_SETTINGS_VERSION,
        "window": {
            "start_minimized": True,
            "minimize_to_tray": True,
            "close_to_tray": False,
        },
        "startup": {"auto_start_bot": True, "operation_mode": "always_on"},
        "ai": {
            "history_max_entries": 100, "context_max_entries": 5,
            "provider": None, "deepseek_selected_model": None, "deepseek_fallback_model": None,
            "openai_selected_model": None, "openai_fallback_model": None,
            "setup": None, "setup_guide_dismissed": False, "setup_guide_ai_skipped": False,
            "cooldown_bypass_user_id": None,
            "fallback_model": None,
            "memory_enabled": False,
            "selected_model": None,
            "response_language": {
                "mode": "auto", "allowed_languages": ["en", "uk", "ru"],
                "fallback_language": "en",
            },
        },
        "twitch": {
            "client_id": None,
            "bot_username": None,
            "bot_user_id": None,
            "channel": None,
            "channel_user_id": None,
            "presets": [],
            "selected_preset_id": None,
        },
        "interface": {"language": "en"},
    }
    assert list(tmp_path.glob(".app_settings.json.*.tmp")) == []


def test_failed_app_settings_save_keeps_previous_state(tmp_path, monkeypatch) -> None:
    store = AppSettingsStore(ConfigFile(tmp_path / "app_settings.json"))

    def fail_save(*args, **kwargs) -> None:
        raise OSError("expected write failure")

    monkeypatch.setattr("app.app_settings.save_app_settings", fail_save)

    with pytest.raises(OSError, match="expected write failure"):
        store.update_desktop(
            start_minimized=True,
            minimize_to_tray=True,
            close_to_tray=True,
            auto_start_bot=False,
        )

    assert store.snapshot() == AppSettings()


def test_twitch_app_settings_are_validated_persisted_and_reloaded(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    store = AppSettingsStore(ConfigFile(settings_path))

    updated = store.update_twitch(channel=" #TestChannel ", channel_user_id=" 200 ")

    assert updated.twitch == TwitchSettings(
        channel="testchannel",
        channel_user_id="200",
    )
    assert AppSettingsStore(ConfigFile(settings_path)).snapshot().twitch == updated.twitch
    payload = read_section(settings_path, "app")
    assert payload["twitch"] == {
        "client_id": None,
        "bot_username": None,
        "bot_user_id": None,
        "channel": "testchannel",
        "channel_user_id": "200",
        "presets": [],
        "selected_preset_id": None,
    }


def test_twitch_presets_are_non_secret_local_metadata_and_can_be_reset(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    store = AppSettingsStore(ConfigFile(settings_path))

    updated, preset = store.save_twitch_preset(
        display_name=" Personal test ",
        channel=" TestChannel ",
        channel_user_id=" 200 ",
    )

    assert preset.display_name == "Personal test"
    assert updated.twitch == TwitchSettings(
        channel="testchannel",
        channel_user_id="200",
        presets=(preset,),
        selected_preset_id=preset.id,
    )
    payload = read_section(settings_path, "app")
    assert payload["twitch"]["presets"] == [
        {
            "id": preset.id,
            "display_name": "Personal test",
            "channel": "testchannel",
            "channel_user_id": "200",
        }
    ]
    assert "token" not in json.dumps(payload).lower()
    assert AppSettingsStore(ConfigFile(settings_path)).snapshot().twitch == updated.twitch

    removed = store.delete_twitch_preset(preset.id)
    assert removed.twitch == TwitchSettings(
        channel="testchannel",
        channel_user_id="200",
    )


def test_twitch_preset_validation_ignores_bad_entries_and_stale_selection(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings_path = tmp_path / "app_settings.json"
    write_section(settings_path, "app", {
                "version": APP_SETTINGS_VERSION,
                "twitch": {
                    "channel": "workchannel",
                    "channel_user_id": "300",
                    "selected_preset_id": "missing",
                    "presets": [
                        {
                            "id": "work",
                            "display_name": "Work",
                            "channel": "workchannel",
                            "channel_user_id": "300",
                        },
                        {
                            "id": "bad id",
                            "display_name": "Broken",
                            "channel": "bad channel",
                            "channel_user_id": "secret",
                        },
                    ],
                },
            })

    with caplog.at_level(logging.WARNING):
        settings = load_app_settings(ConfigFile(settings_path).section("app"))

    assert settings.twitch == TwitchSettings(
        channel="workchannel",
        channel_user_id="300",
        presets=(
            TwitchConnectionPreset(
                id="work",
                display_name="Work",
                channel="workchannel",
                channel_user_id="300",
            ),
        ),
    )
    assert "invalid Twitch connection preset" in caplog.text
    assert "invalid Twitch preset selection" in caplog.text


@pytest.mark.parametrize(
    ("channel", "channel_user_id"),
    [("", "200"), ("bad channel", "200"), ("channel", "not-a-number")],
)
def test_twitch_app_settings_reject_invalid_values(
    tmp_path,
    channel: str,
    channel_user_id: str,
) -> None:
    store = AppSettingsStore(ConfigFile(tmp_path / "app_settings.json"))

    with pytest.raises(ValueError):
        store.update_twitch(channel=channel, channel_user_id=channel_user_id)

    assert store.snapshot().twitch == TwitchSettings()


def test_incomplete_twitch_override_falls_back_safely(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    write_section(settings_path, "app", {
                "version": APP_SETTINGS_VERSION,
                "twitch": {"channel": "testchannel"},
            })

    assert load_app_settings(ConfigFile(settings_path).section("app")).twitch == TwitchSettings()


def test_legacy_gemini_model_settings_survive_a_memory_update(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    write_section(settings_path, "app", {"version": APP_SETTINGS_VERSION, "ai": {
        "provider": "gemini", "selected_model": " custom-gemini-model ", "fallback_model": "gemini-3.1-flash-lite",
    }})
    store = AppSettingsStore(ConfigFile(settings_path))

    assert store.snapshot().ai == AISettings(
        provider="gemini",
        selected_model="custom-gemini-model",
        fallback_model="gemini-3.1-flash-lite",
    )
    memory_updated = store.update_ai_memory(enabled=False)
    assert AppSettingsStore(ConfigFile(settings_path)).snapshot().ai == memory_updated.ai
    assert read_section(settings_path, "app")["ai"] == {
        "history_max_entries": 100, "context_max_entries": 5,
        "provider": "gemini", "deepseek_selected_model": None, "deepseek_fallback_model": None,
        "openai_selected_model": None, "openai_fallback_model": None,
        "setup": None, "setup_guide_dismissed": False, "setup_guide_ai_skipped": False,
        "cooldown_bypass_user_id": None,
        "fallback_model": "gemini-3.1-flash-lite",
        "memory_enabled": False,
        "selected_model": "custom-gemini-model",
        "response_language": {
            "mode": "auto", "allowed_languages": ["en", "uk", "ru"],
            "fallback_language": "en",
        },
    }

    assert memory_updated.ai == AISettings(
        provider="gemini",
        memory_enabled=False,
        selected_model="custom-gemini-model",
        fallback_model="gemini-3.1-flash-lite",
    )


def test_incomplete_gemini_model_override_falls_back_safely(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    write_section(settings_path, "app", {
                "version": APP_SETTINGS_VERSION,
                "ai": {"selected_model": "gemini-custom"},
            })

    assert load_app_settings(ConfigFile(settings_path).section("app")).ai == AISettings()


def test_bridge_reads_and_updates_desktop_settings(tmp_path) -> None:
    store = AppSettingsStore(ConfigFile(tmp_path / "app_settings.json"))
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace()),
        app_settings=store,
    )

    assert bridge.get_app_settings() == {
        "ok": True,
        "settings": {
            "start_minimized": False,
            "minimize_to_tray": False,
            "close_to_tray": False,
            "auto_start_bot": False,
            "tray_available": sys.platform == "win32",
        },
    }
    assert bridge.update_app_settings(True, True, False, True) == {"ok": True}
    assert store.snapshot() == AppSettings(
        window=WindowSettings(start_minimized=True, minimize_to_tray=True),
        startup=StartupSettings(auto_start_bot=True),
    )
    assert bridge.update_app_settings("true", False, False, False) == {
        "ok": False,
        "error_code": "validation.type",
        "error_params": {"field": "start_minimized", "expected": "boolean"},
    }


def test_bridge_persists_ai_memory_before_updating_runtime(tmp_path) -> None:
    store = AppSettingsStore(ConfigFile(tmp_path / "app_settings.json"))
    runtime_state = SimpleNamespace(ai_memory_enabled=True)
    runtime_state.set_ai_memory_enabled = lambda enabled: setattr(
        runtime_state,
        "ai_memory_enabled",
        enabled,
    )
    backend = SimpleNamespace(
        application=SimpleNamespace(
            services=SimpleNamespace(runtime_state=runtime_state)
        ),
        submit=complete_bridge_coroutine,
    )
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, backend),
        app_settings=store,
    )

    assert bridge.set_ai_memory_enabled(False) == {"ok": True}
    assert runtime_state.ai_memory_enabled is False
    assert store.snapshot().ai == AISettings(memory_enabled=False)


def test_bridge_does_not_change_runtime_when_ai_memory_save_fails(
    tmp_path,
    monkeypatch,
) -> None:
    store = AppSettingsStore(ConfigFile(tmp_path / "app_settings.json"))
    runtime_state = SimpleNamespace(ai_memory_enabled=True)
    runtime_state.set_ai_memory_enabled = lambda enabled: setattr(
        runtime_state,
        "ai_memory_enabled",
        enabled,
    )
    backend = SimpleNamespace(
        application=SimpleNamespace(
            services=SimpleNamespace(runtime_state=runtime_state)
        ),
        submit=complete_bridge_coroutine,
    )
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, backend),
        app_settings=store,
    )

    def fail_update(**kwargs) -> None:
        raise OSError("expected failure")

    monkeypatch.setattr(store, "update_ai_memory", fail_update)

    assert bridge.set_ai_memory_enabled(False) == {
        "ok": False,
        "error_code": "webview_host.could_not_save_ai_memory_setting", "error_params": {},
    }
    assert runtime_state.ai_memory_enabled is True


def test_interface_language_defaults_to_english_and_persists(tmp_path) -> None:
    path = tmp_path / "app_settings.json"
    store = AppSettingsStore(ConfigFile(path))
    assert store.snapshot().interface.language == "en"
    store.update_desktop(start_minimized=True, minimize_to_tray=False, close_to_tray=False, auto_start_bot=False)
    store.update_interface_language("uk")
    # Unrelated saves keep the chosen language.
    store.update_desktop(start_minimized=False, minimize_to_tray=False, close_to_tray=False, auto_start_bot=True)
    reloaded = AppSettingsStore(ConfigFile(path)).snapshot()
    assert reloaded.interface.language == "uk"
    assert reloaded.startup.auto_start_bot is True
    assert read_section(path, "app")["interface"] == {"language": "uk"}


@pytest.mark.parametrize("value", ["de", "", None, 1, "EN"])
def test_interface_language_rejects_unknown_values(tmp_path, value) -> None:
    store = AppSettingsStore(ConfigFile(tmp_path / "app_settings.json"))
    with pytest.raises(ValueError):
        store.update_interface_language(value)
    assert store.snapshot().interface.language == "en"


def test_invalid_saved_interface_language_falls_back_to_english(tmp_path) -> None:
    path = tmp_path / "app_settings.json"
    write_section(path, "app", {"version": APP_SETTINGS_VERSION, "interface": {"language": "xx"},
                                "startup": {"auto_start_bot": True}})
    settings = load_app_settings(ConfigFile(path).section("app"))
    assert settings.interface.language == "en"
    assert settings.startup.auto_start_bot is True
