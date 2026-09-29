"""Focused tests for local desktop application settings."""

import json
import logging
from types import SimpleNamespace
from typing import cast

import pytest

from app.app_settings import AppSettings, AppSettingsStore, load_app_settings
from app.webview_host import AsyncioBackendHost, WebUIBridge


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
                "start_minimized": True,
                "minimize_to_tray": "yes",
                "close_to_tray": False,
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        settings = load_app_settings(settings_path)

    assert settings == AppSettings(start_minimized=True)
    assert "invalid desktop setting" in caplog.text


@pytest.mark.parametrize("file_content", ["", "[]", "{not-json"])
def test_malformed_app_settings_file_does_not_block_startup(
    tmp_path,
    file_content: str,
) -> None:
    settings_path = tmp_path / "app_settings.json"
    settings_path.write_text(file_content, encoding="utf-8")

    assert load_app_settings(settings_path) == AppSettings()


def test_app_settings_store_saves_atomically_and_reloads(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.json"
    store = AppSettingsStore(settings_path)

    updated = store.update(
        start_minimized=True,
        minimize_to_tray=True,
        close_to_tray=False,
    )

    assert updated == AppSettings(start_minimized=True, minimize_to_tray=True)
    assert AppSettingsStore(settings_path).snapshot() == updated
    assert list(tmp_path.glob(".app_settings.json.*.tmp")) == []


def test_failed_app_settings_save_keeps_previous_state(tmp_path, monkeypatch) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")

    def fail_save(*args, **kwargs) -> None:
        raise OSError("expected write failure")

    monkeypatch.setattr("app.app_settings.save_app_settings", fail_save)

    with pytest.raises(OSError, match="expected write failure"):
        store.update(
            start_minimized=True,
            minimize_to_tray=True,
            close_to_tray=True,
        )

    assert store.snapshot() == AppSettings()


def test_app_settings_store_rejects_non_boolean_values(tmp_path) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")

    with pytest.raises(ValueError, match="boolean"):
        store.update(
            start_minimized="true",
            minimize_to_tray=False,
            close_to_tray=False,
        )


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
        },
    }
    assert bridge.update_app_settings(True, True, False) == {"ok": True}
    assert store.snapshot() == AppSettings(start_minimized=True, minimize_to_tray=True)
    assert bridge.update_app_settings("true", False, False) == {
        "ok": False,
        "error": "Desktop settings must be boolean values.",
    }
