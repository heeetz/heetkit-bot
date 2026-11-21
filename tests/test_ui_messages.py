"""UI language support on the backend (task 2.2): message codes, tray text, preference."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from app.app_settings import AppSettingsStore
from app.system_tray import TRAY_TEXT, SystemTray, tray_status_text, tray_text
from app.ui_messages import MESSAGE_FIELDS, MESSAGES, annotate_error, message_code
from app.webview_host import AsyncioBackendHost, DesktopController, WebUIBridge

ROOT = Path(__file__).parents[1]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _catalog_block(source: str, language: str) -> dict[str, str]:
    start = source.index(f"\n  {language}: {{\n")
    end = source.index("\n  },", start)
    entries = re.findall(r'^    "([^"]+)": "((?:[^"\\]|\\.)*)",$', source[start:end], re.MULTILINE)
    return {key: bytes(value, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
            if "\\" in value else value for key, value in entries}


def test_frontend_catalog_matches_backend_messages() -> None:
    source = (ROOT / "frontend/src/i18n/backendErrors.ts").read_text(encoding="utf-8")
    english = _catalog_block(source, "en")
    assert english == MESSAGES
    for language in ("uk", "ru"):
        translated = _catalog_block(source, language)
        assert translated.keys() == MESSAGES.keys()
        for code, template in MESSAGES.items():
            assert sorted(PLACEHOLDER.findall(translated[code])) == sorted(PLACEHOLDER.findall(template)), code
            assert translated[code] and translated[code] != template or code in {"timeout"}, code


def test_registered_messages_still_exist_in_backend_sources() -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "app").rglob("*.py")
                        if path.name != "ui_messages.py")
    for code, template in MESSAGES.items():
        # The longest literal run of each template must still be written somewhere in app/.
        literal = max(PLACEHOLDER.split(template)[::2], key=len)
        assert literal in sources or literal.replace("'", "\\'") in sources, code


def test_annotation_adds_codes_and_parameters() -> None:
    assert annotate_error({"ok": False, "error": "Desktop settings are not configured."}) == {
        "ok": False, "error": "Desktop settings are not configured.",
        "error_code": "management.desktop_settings_not_configured",
    }
    annotated = annotate_error({"ok": False, "error": "Command name or alias already exists: hello"})
    assert annotated["error_code"] == "custom_commands.command_name_alias_already_exists"
    assert annotated["error_params"] == {"name": "hello"}
    # Unknown text keeps only the English message; existing codes are not replaced.
    assert annotate_error({"ok": False, "error": "Synthetic unknown failure."}) == {
        "ok": False, "error": "Synthetic unknown failure."}
    coded = {"ok": False, "error": "The provider rejected the configured key.", "error_code": "credential_rejected"}
    assert annotate_error(coded) is coded
    assert annotate_error({"ok": True}) == {"ok": True}
    update = annotate_error({"ok": True, "automatic_update_reason": "Publisher verification is unavailable. Install the update manually."})
    assert update["automatic_update_reason_code"] == "webview_host.publisher_verification_unavailable_install_update_manually"
    assert "error_code" not in update
    assert MESSAGE_FIELDS == ("error", "automatic_update_reason")


def test_settings_validation_errors_are_coded(tmp_path) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")
    with pytest.raises(ValueError) as error:
        store.update_twitch(channel="bad channel", channel_user_id="1")
    assert message_code(str(error.value)) == ("app_settings.twitch_target_channel_not_contain_whitespace", {})
    with pytest.raises(ValueError) as error:
        store.update_interface_language("de")
    assert message_code(str(error.value)) == ("app_settings.choose_english_ukrainian_russian", {})


def test_tray_text_has_every_label_in_every_language() -> None:
    keys = TRAY_TEXT["en"].keys()
    for language in ("uk", "ru"):
        assert TRAY_TEXT[language].keys() == keys
        for key in keys:
            assert PLACEHOLDER.findall(TRAY_TEXT[language][key]) == PLACEHOLDER.findall(TRAY_TEXT["en"][key])
    assert tray_text("xx", "open") == "Open"
    assert tray_text("uk", "stop") == "Зупинити бота"
    assert tray_text("ru", "update") == "Доступно обновление"


@pytest.mark.parametrize(("language", "status", "expected"), [
    ("en", {"running": True, "twitch_connection_state": "connected", "channel": "#synthetic"}, "Connected · #synthetic"),
    ("uk", {"running": True, "twitch_connection_state": "connected", "channel": "synthetic"}, "Підключено · #synthetic"),
    ("ru", {"running": True, "twitch_connection_state": "reconnecting", "channel": "synthetic"}, "Переподключение…"),
    ("ru", {"running": False, "twitch_connection_state": "stopped", "channel": "synthetic"}, "Остановлен"),
    ("en", {"running": False, "twitch_connection_state": "failed"}, "Connection failed"),
    ("uk", None, "Зупинено"),
])
def test_tray_status_line(language, status, expected) -> None:
    assert tray_status_text(language, status) == expected


def test_tray_menu_items_follow_language_status_and_update(monkeypatch) -> None:
    state = {"language": "ru", "running": True, "update": False}
    opened: list[str] = []
    tray = SystemTray(
        on_open=lambda: opened.append("open"), on_toggle_bot=lambda: None, on_exit=lambda: None,
        is_bot_running=lambda: state["running"], language=lambda: state["language"],
        status=lambda: {"running": state["running"], "twitch_connection_state": "connected", "channel": "synthetic"},
        update_available=lambda: state["update"], on_open_update=lambda: opened.append("update"),
    )
    assert tray._status_label(None) == "Подключено · #synthetic"
    assert tray._toggle_label(None) == "Остановить бота"
    assert tray._open_label(None) == "Открыть" and tray._exit_label(None) == "Выйти"
    assert tray._show_update(None) is False
    state.update(language="uk", update=True, running=False)
    assert tray._show_update(None) is True
    assert tray._update_label(None) == "Доступне оновлення"
    assert tray._toggle_label(None) == "Запустити бота"
    tray._handle_update(None, None)
    assert opened == ["update"]
    state["language"] = "de"
    assert tray._open_label(None) == "Open"


class _Tray:
    def __init__(self) -> None:
        self.update_calls = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def update_menu(self) -> None:
        self.update_calls += 1


class _RuntimeState:
    running = False
    twitch_connection_state = "stopped"

    def status(self) -> tuple[bool, int]:
        return self.running, 0


def _controller(tmp_path):
    runtime_state = _RuntimeState()
    backend = SimpleNamespace(
        application=SimpleNamespace(services=SimpleNamespace(runtime_state=runtime_state),
                                    settings=SimpleNamespace(twitch_channel="synthetic")),
        startup_pending=False, close=lambda: None,
    )
    store = AppSettingsStore(tmp_path / "app_settings.json")
    bridge = WebUIBridge.__new__(WebUIBridge)
    bridge._app_settings = store
    bridge._update_available = False
    bridge._logger = SimpleNamespace(exception=lambda *args, **kwargs: None)
    tray = _Tray()
    controller = DesktopController(cast(AsyncioBackendHost, backend), bridge, store, tray=tray)
    bridge._controller = controller
    return controller, bridge, tray, runtime_state, store


def test_interface_language_bridge_persists_and_refreshes_tray(tmp_path) -> None:
    controller, bridge, tray, runtime_state, store = _controller(tmp_path)
    controller._tray_supported = True
    controller.start_tray()
    try:
        assert bridge.get_interface_language() == {"ok": True, "language": "en"}
        assert tray.update_calls == 0
        assert bridge.set_interface_language("ru") == {"ok": True}
        assert store.snapshot().interface.language == "ru"
        assert bridge.get_interface_language() == {"ok": True, "language": "ru"}
        assert tray.update_calls == 1
        # No change, no rebuild; a status change rebuilds once.
        controller.refresh_tray()
        assert tray.update_calls == 1
        runtime_state.running = True
        runtime_state.twitch_connection_state = "connected"
        controller.refresh_tray()
        assert tray.update_calls == 2
        rejected = bridge.set_interface_language("de")
        assert rejected["ok"] is False
        assert annotate_error(rejected)["error_code"] == "app_settings.choose_english_ukrainian_russian"
        assert store.snapshot().interface.language == "ru"
    finally:
        controller._tray_refresh_stop.set()


def test_update_item_follows_the_last_update_check(tmp_path) -> None:
    controller, bridge, tray, _, _ = _controller(tmp_path)
    assert controller.update_available() is False
    bridge._update_available = True
    assert controller.update_available() is True
