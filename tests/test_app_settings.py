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
    AIModelPair,
    AISettings,
    AppSettings,
    AppSettingsStore,
    ChatSettings,
    CustomAIConnection,
    StartupSettings,
    TwitchConnectionPreset,
    TwitchSettings,
    WindowSettings,
    load_app_settings,
)
from app.errors import UserError
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


@pytest.mark.parametrize(("content", "expected"), [
    (None, AppSettings()),
    ("", AppSettings(startup=StartupSettings(operation_mode="disabled"))),
    ("[]", AppSettings(startup=StartupSettings(operation_mode="disabled"))),
    ("{not-json", AppSettings(startup=StartupSettings(operation_mode="disabled"))),
    ({"version": 99, "window": {"start_minimized": True}}, AppSettings(startup=StartupSettings(operation_mode="disabled"))),
    ({"version": APP_SETTINGS_VERSION, "twitch": {"channel": "testchannel"}}, AppSettings()),
    ({"version": APP_SETTINGS_VERSION, "ai": {"selected_model": "gemini-custom"}}, AppSettings()),
], ids=["missing", "empty", "array", "malformed", "future-version", "incomplete-twitch", "incomplete-model"])
def test_missing_malformed_or_incomplete_app_settings_use_safe_defaults(tmp_path, content, expected) -> None:
    settings_path = tmp_path / "app_settings.json"
    if isinstance(content, str):
        settings_path.write_text(content, encoding="utf-8")
    elif content is not None:
        write_section(settings_path, "app", content)

    assert load_app_settings(ConfigFile(settings_path).section("app")) == expected


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
                "startup": {"auto_start_bot": "yes", "paused": "yes"},
                "ai": {"memory_enabled": "yes"},
                "chat": {"reply_interval_seconds": 61},
            })

    with caplog.at_level(logging.WARNING):
        settings = load_app_settings(ConfigFile(settings_path).section("app"))

    assert settings == AppSettings(window=WindowSettings(start_minimized=True))
    assert "invalid application setting" in caplog.text


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
    store.update_paused(True)
    updated = store.update_reply_interval(12)
    with pytest.raises(ValueError):
        store.update_reply_interval(61)

    assert updated == AppSettings(
        window=WindowSettings(start_minimized=True, minimize_to_tray=True),
        startup=StartupSettings(auto_start_bot=True, paused=True),
        ai=AISettings(memory_enabled=False),
        chat=ChatSettings(reply_interval_seconds=12),
    )
    assert AppSettingsStore(ConfigFile(settings_path)).snapshot() == updated
    assert read_section(settings_path, "app") == {
        "version": APP_SETTINGS_VERSION,
        "window": {
            "start_minimized": True,
            "minimize_to_tray": True,
            "close_to_tray": False,
        },
        "startup": {"auto_start_bot": True, "operation_mode": "always_on", "paused": True},
        "ai": {
            "history_max_entries": 100, "context_max_entries": 5,
            "provider": None, "providers": {},
            "setup": None, "setup_guide_dismissed": False, "setup_guide_ai_skipped": False,
            "cooldown_bypass_user_id": None,
            "memory_enabled": False,
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
        "chat": {"reply_interval_seconds": 12},
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


def test_legacy_flat_model_settings_move_to_providers_on_the_next_save(tmp_path) -> None:
    settings_path = tmp_path / "config.json"
    write_section(settings_path, "app", {"version": APP_SETTINGS_VERSION, "ai": {
        "provider": "gemini", "selected_model": " custom-gemini-model ", "fallback_model": "gemini-3.1-flash-lite",
        "deepseek_selected_model": "deepseek-flash", "deepseek_fallback_model": "deepseek-v4-pro",
        "openai_selected_model": None, "openai_fallback_model": None,
    }})
    store = AppSettingsStore(ConfigFile(settings_path))
    providers = {"gemini": AIModelPair("custom-gemini-model", "gemini-3.1-flash-lite"),
                 "deepseek": AIModelPair("deepseek-flash", "deepseek-v4-pro")}

    assert store.snapshot().ai == AISettings(provider="gemini", providers=providers)
    memory_updated = store.update_ai_memory(enabled=False)
    assert AppSettingsStore(ConfigFile(settings_path)).snapshot().ai == memory_updated.ai
    saved_ai = read_section(settings_path, "app")["ai"]
    assert saved_ai["providers"] == {
        "gemini": {"selected_model": "custom-gemini-model", "fallback_model": "gemini-3.1-flash-lite"},
        "deepseek": {"selected_model": "deepseek-flash", "fallback_model": "deepseek-v4-pro"}}
    assert not any(key.endswith(("selected_model", "fallback_model")) for key in saved_ai)
    # The pre-migration file is kept once as a recovery copy.
    assert len(list(tmp_path.glob("config.json.*.recovery"))) == 1
    assert memory_updated.ai == AISettings(provider="gemini", memory_enabled=False, providers=providers)


LOCAL_ONLY, PUBLIC_HTTPS, BLOCKED, INVALID = ("ai_models.custom_base_url_http_local_only",
    "ai_models.custom_base_url_server_public_https", "ai_models.custom_base_url_address_blocked",
    "ai_models.custom_base_url_invalid")


# Columns: Desktop ("local"), Server ("public"), Server with private networks ("private").
@pytest.mark.parametrize(("url", "local", "public", "private"), [
    ("http://localhost:1234/v1/", "http://localhost:1234/v1", PUBLIC_HTTPS, "http://localhost:1234/v1"),
    ("http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1", PUBLIC_HTTPS, "http://127.0.0.1:1234/v1"),
    ("http://[::1]:8080", "http://[::1]:8080", PUBLIC_HTTPS, "http://[::1]:8080"),
    ("https://llm.example.com/v1", "https://llm.example.com/v1", "https://llm.example.com/v1", "https://llm.example.com/v1"),
    ("http://192.168.1.20:1234/v1", LOCAL_ONLY, PUBLIC_HTTPS, "http://192.168.1.20:1234/v1"),
    ("http://100.101.102.103:1234/v1", LOCAL_ONLY, PUBLIC_HTTPS, "http://100.101.102.103:1234/v1"),
    ("http://localhost.example.com/v1", LOCAL_ONLY, PUBLIC_HTTPS, "http://localhost.example.com/v1"),
    ("https://10.0.0.5/v1", "https://10.0.0.5/v1", PUBLIC_HTTPS, "https://10.0.0.5/v1"),
    ("https://169.254.169.254/v1", "https://169.254.169.254/v1", BLOCKED, BLOCKED),
    ("https://user:secret@llm.example.com/v1", INVALID, INVALID, INVALID),
    ("https://llm.example.com/v1?key=1", INVALID, INVALID, INVALID),
    ("ftp://localhost/v1", INVALID, INVALID, INVALID),
    ("https://llm.example.com:99999", INVALID, INVALID, INVALID),
    ("localhost:1234", INVALID, INVALID, INVALID),
])
def test_custom_connection_address_policy_per_host(tmp_path, url, local, public, private) -> None:
    from app.services.custom_ai_network import validate_custom_url_for_host
    for policy, expected in (("local", local), ("public", public), ("private", private)):
        if expected.startswith("ai_models."):
            with pytest.raises(UserError) as error:
                validate_custom_url_for_host(url, policy)
            assert error.value.code == expected
        else:
            assert validate_custom_url_for_host(url, policy) == expected
    settings_path = tmp_path / "config.json"
    store = AppSettingsStore(ConfigFile(settings_path))
    if private.startswith("ai_models.") and local.startswith("ai_models."):
        with pytest.raises(UserError):
            store.update_custom_ai_connection(url)
        assert not settings_path.exists()
        return
    # The profile keeps any well-formed address; each host checks its policy on save and connect.
    accepted = private if not private.startswith("ai_models.") else local
    store.update_custom_ai_connection(url)
    assert read_section(settings_path, "app")["ai"]["providers"] == {"custom": {"base_url": accepted}}
    assert AppSettingsStore(ConfigFile(settings_path)).snapshot().ai.providers == {"custom": CustomAIConnection(accepted)}
    assert store.update_custom_ai_connection(None).ai.providers == {}


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


def ai_memory_bridge(store):
    runtime_state = SimpleNamespace(ai_memory_enabled=True)
    runtime_state.set_ai_memory_enabled = lambda enabled: setattr(runtime_state, "ai_memory_enabled", enabled)
    backend = SimpleNamespace(application=SimpleNamespace(services=SimpleNamespace(runtime_state=runtime_state)),
                              submit=complete_bridge_coroutine)
    return WebUIBridge(cast(AsyncioBackendHost, backend), app_settings=store), runtime_state


def test_bridge_persists_ai_memory_before_updating_runtime(tmp_path, monkeypatch) -> None:
    store = AppSettingsStore(ConfigFile(tmp_path / "app_settings.json"))
    bridge, runtime_state = ai_memory_bridge(store)
    with monkeypatch.context() as patch:
        patch.setattr(store, "update_ai_memory", lambda **kwargs: (_ for _ in ()).throw(OSError("expected failure")))
        assert bridge.set_ai_memory_enabled(False) == {
            "ok": False, "error_code": "webview_host.could_not_save_ai_memory_setting", "error_params": {},
        }
    assert runtime_state.ai_memory_enabled is True

    assert bridge.set_ai_memory_enabled(False) == {"ok": True}
    assert runtime_state.ai_memory_enabled is False
    assert store.snapshot().ai == AISettings(memory_enabled=False)


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
