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


def complete_bridge_coroutine(coroutine) -> Future:
    future: Future = Future()
    try:
        future.set_result(asyncio.run(coroutine))
    except BaseException as error:
        future.set_exception(error)
    return future


def test_missing_app_settings_file_uses_safe_defaults(tmp_path) -> None:
    settings = load_app_settings(tmp_path / "app_settings.json")

    assert settings == AppSettings()


def test_partial_and_invalid_app_settings_fall_back_individually(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "version": APP_SETTINGS_VERSION,
                "window": {
                    "start_minimized": True,
                    "minimize_to_tray": "yes",
                    "close_to_tray": False,
                },
                "startup": {"auto_start_bot": "yes"},
                "ai": {"memory_enabled": "yes"},
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        settings = load_app_settings(settings_path)

    assert settings == AppSettings(window=WindowSettings(start_minimized=True))
    assert "invalid application setting" in caplog.text


def test_legacy_flat_window_settings_remain_compatible(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "start_minimized": True,
                "minimize_to_tray": True,
                "close_to_tray": False,
            }
        ),
        encoding="utf-8",
    )

    assert load_app_settings(settings_path) == AppSettings(
        window=WindowSettings(start_minimized=True, minimize_to_tray=True)
    )
    store = AppSettingsStore(settings_path)
    updated = store.update_ai_memory(enabled=False)

    assert updated.window == WindowSettings(
        start_minimized=True,
        minimize_to_tray=True,
    )
    assert json.loads(settings_path.read_text(encoding="utf-8"))["version"] == (
        APP_SETTINGS_VERSION
    )


@pytest.mark.parametrize("file_content", ["", "[]", "{not-json"])
def test_malformed_app_settings_file_does_not_block_startup(
    tmp_path,
    file_content: str,
) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(file_content, encoding="utf-8")

    assert load_app_settings(settings_path) == AppSettings()


def test_unknown_app_settings_version_uses_defaults(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(
        json.dumps({"version": 99, "window": {"start_minimized": True}}),
        encoding="utf-8",
    )

    assert load_app_settings(settings_path) == AppSettings()


def test_app_settings_store_saves_atomically_and_reloads(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    store = AppSettingsStore(settings_path)

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
    assert AppSettingsStore(settings_path).snapshot() == updated
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "version": APP_SETTINGS_VERSION,
        "window": {
            "start_minimized": True,
            "minimize_to_tray": True,
            "close_to_tray": False,
        },
        "startup": {"auto_start_bot": True},
        "ai": {
            "cooldown_bypass_user_id": None,
            "fallback_model": None,
            "memory_enabled": False,
            "selected_model": None,
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
    }
    assert list(tmp_path.glob(".app_settings.json.*.tmp")) == []


def test_failed_app_settings_save_keeps_previous_state(tmp_path, monkeypatch) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")

    def fail_save(*args, **kwargs) -> None:
        raise OSError("expected write failure")

    monkeypatch.setattr("app.app_settings.save_app_settings", fail_save)

    with pytest.raises(OSError, match="expected write failure"):
        store.update_window(
            start_minimized=True,
            minimize_to_tray=True,
            close_to_tray=True,
        )

    assert store.snapshot() == AppSettings()


def test_app_settings_store_rejects_non_boolean_values(tmp_path) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")

    with pytest.raises(ValueError, match="boolean"):
        store.update_window(
            start_minimized="true",
            minimize_to_tray=False,
            close_to_tray=False,
        )


def test_twitch_app_settings_are_validated_persisted_and_reloaded(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    store = AppSettingsStore(settings_path)

    updated = store.update_twitch(channel=" #TestChannel ", channel_user_id=" 200 ")

    assert updated.twitch == TwitchSettings(
        channel="testchannel",
        channel_user_id="200",
    )
    assert AppSettingsStore(settings_path).snapshot().twitch == updated.twitch
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
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
    store = AppSettingsStore(settings_path)

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
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["twitch"]["presets"] == [
        {
            "id": preset.id,
            "display_name": "Personal test",
            "channel": "testchannel",
            "channel_user_id": "200",
        }
    ]
    assert "token" not in json.dumps(payload).lower()
    assert AppSettingsStore(settings_path).snapshot().twitch == updated.twitch

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
    settings_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        settings = load_app_settings(settings_path)

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
    store = AppSettingsStore(tmp_path / "app_settings.json")

    with pytest.raises(ValueError):
        store.update_twitch(channel=channel, channel_user_id=channel_user_id)

    assert store.snapshot().twitch == TwitchSettings()


def test_incomplete_twitch_override_falls_back_safely(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "version": APP_SETTINGS_VERSION,
                "twitch": {"channel": "testchannel"},
            }
        ),
        encoding="utf-8",
    )

    assert load_app_settings(settings_path).twitch == TwitchSettings()


def test_gemini_model_settings_are_validated_persisted_and_reloaded(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    store = AppSettingsStore(settings_path)

    updated = store.update_ai_models(
        selected_model=" custom-gemini-model ",
        fallback_model="gemini-3.1-flash-lite",
    )

    assert updated.ai == AISettings(
        selected_model="custom-gemini-model",
        fallback_model="gemini-3.1-flash-lite",
    )
    assert AppSettingsStore(settings_path).snapshot().ai == updated.ai
    assert json.loads(settings_path.read_text(encoding="utf-8"))["ai"] == {
        "cooldown_bypass_user_id": None,
        "fallback_model": "gemini-3.1-flash-lite",
        "memory_enabled": True,
        "selected_model": "custom-gemini-model",
    }

    memory_updated = store.update_ai_memory(enabled=False)
    assert memory_updated.ai == AISettings(
        memory_enabled=False,
        selected_model="custom-gemini-model",
        fallback_model="gemini-3.1-flash-lite",
    )


@pytest.mark.parametrize(
    ("selected", "fallback"),
    [
        ("", "gemini-fallback"),
        ("bad model", "gemini-fallback"),
        ("gemini-same", "gemini-same"),
    ],
)
def test_gemini_model_settings_reject_invalid_values(
    tmp_path,
    selected: str,
    fallback: str,
) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")

    with pytest.raises(ValueError):
        store.update_ai_models(selected_model=selected, fallback_model=fallback)

    assert store.snapshot().ai == AISettings()


def test_incomplete_gemini_model_override_falls_back_safely(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "version": APP_SETTINGS_VERSION,
                "ai": {"selected_model": "gemini-custom"},
            }
        ),
        encoding="utf-8",
    )

    assert load_app_settings(settings_path).ai == AISettings()


def test_bridge_reads_and_updates_desktop_settings(tmp_path) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")
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
        "error": "Desktop settings must be boolean values.",
    }


def test_bridge_persists_ai_memory_before_updating_runtime(tmp_path) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")
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
    store = AppSettingsStore(tmp_path / "app_settings.json")
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
        "error": "Could not save AI memory setting.",
    }
    assert runtime_state.ai_memory_enabled is True
