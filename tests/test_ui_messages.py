"""UI language support on the backend (task 2.2): message codes, tray text, preference."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from app import webview_host
from app.app_settings import AppSettingsStore
from app.system_tray import TRAY_TEXT, SystemTray, tray_status_text, tray_text
from app.errors import UserError, UserOSError, UserRuntimeError, UserTimeoutError, error_result
from app.management_api import ManagementAPI
from app.operations import collect, operation
from app.ui_messages import MESSAGES
from app.webview_host import AsyncioBackendHost, DesktopController, WebUIBridge

ROOT = Path(__file__).parents[1]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _catalog_block(source: str, language: str) -> dict[str, str]:
    start = source.index(f"\n  {language}: {{\n")
    end = source.index("\n  },", start)
    entries = re.findall(r'^    "([^"]+)": "((?:[^"\\]|\\.)*)",$', source[start:end], re.MULTILINE)
    return {key: json.loads(f'"{value}"') for key, value in entries}


def _literal_codes(value: ast.expr) -> list[str]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, ast.IfExp):
        # The condition may contain ordinary strings, such as a filter category.
        return _literal_codes(value.body) + _literal_codes(value.orelse)
    return []


def test_frontend_catalog_matches_backend_messages() -> None:
    source = (ROOT / "frontend/src/i18n/backendErrors.ts").read_text(encoding="utf-8")
    english = _catalog_block(source, "en")
    assert english.keys() == MESSAGES.keys()
    for language in ("uk", "ru"):
        translated = _catalog_block(source, language)
        assert translated.keys() == MESSAGES.keys()
        for code, template in MESSAGES.items():
            parameters = sorted(PLACEHOLDER.findall(template))
            assert sorted(PLACEHOLDER.findall(english[code])) == parameters, code
            assert sorted(PLACEHOLDER.findall(translated[code])) == parameters, code
            assert english[code].strip(), code
            assert translated[code].strip(), code
    used: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        if path.name == "ui_messages.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in MESSAGES:
                used.add(node.value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in {
                        "error_code", "automatic_update_reason_code", "load_error_code",
                    }:
                        for code in _literal_codes(value):
                            assert code in MESSAGES, (path, code)
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", "")
                if name in {"UserError", "UserOSError", "UserRuntimeError", "UserTimeoutError", "InstallationInUseError",
                            "CredentialError", "UpdateCheckError", "TwitchConfigurationError",
                            "AIModelDiscoveryError",
                            "DatabaseMigrationError", "TwitchConnectionError", "TwitchCleanupError", "error_result"}:
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        assert node.args[0].value in MESSAGES, (path, node.args[0].value)
                if name == "FilterValidationError" and len(node.args) >= 3:
                    for code in _literal_codes(node.args[2]):
                        assert code in MESSAGES, (path, code)
                for argument in node.keywords:
                    if argument.arg in {"failure", "validation_failure", "timeout_failure", "cancelled_failure", "fallback"}:
                        if isinstance(argument.value, ast.Constant) and isinstance(argument.value.value, str):
                            assert argument.value.value in MESSAGES, (path, argument.value.value)
    assert used == MESSAGES.keys(), MESSAGES.keys() - used


def test_user_error_preserves_code_parameters_and_legacy_rendering() -> None:
    error = UserError("custom_commands.command_name_alias_already_exists", name="hello")
    assert isinstance(error, ValueError)
    assert str(error) == MESSAGES[error.code].format(**error.params)
    assert error_result(error) == {
        "ok": False, "error_code": "custom_commands.command_name_alias_already_exists",
        "error_params": {"name": "hello"},
    }
    assert "error" not in error_result(ValueError("private diagnostic"))
    assert error_result(ValueError("private diagnostic"))["error_code"] == (
        "webview_host.management_operation_unavailable_check_profile_storage"
    )
    exit_error = UserError("desktop_relaunch.heetkit_setup_failed_exit_code_close", code="42")
    assert exit_error.params == {"code": "42"}
    assert str(exit_error) == MESSAGES[exit_error.code].format(code="42")


def test_settings_validation_errors_are_coded(tmp_path) -> None:
    store = AppSettingsStore(tmp_path / "app_settings.json")
    with pytest.raises(UserError) as error:
        store.update_twitch(channel="bad channel", channel_user_id="1")
    assert error.value.code == "app_settings.twitch_target_channel_not_contain_whitespace"
    with pytest.raises(UserError) as error:
        store.update_interface_language("de")
    assert error.value.code == "app_settings.choose_english_ukrainian_russian"


@pytest.mark.parametrize("passthrough", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("error_type", [UserError, UserOSError, UserRuntimeError, UserTimeoutError])
async def test_both_hosts_serialize_source_codes(monkeypatch, passthrough, asynchronous, error_type) -> None:
    def fail(self):
        raise error_type("custom_commands.command_name_alias_already_exists", name="synthetic")

    async def fail_async(self):
        fail(self)

    method = operation(write=False, passthrough_errors=passthrough)(fail_async if asynchronous else fail)
    operations = type("SyntheticOperations", (), {"fail": method})
    registered = next(iter(collect(operations).values()))
    service = operations()
    server = ManagementAPI.__new__(ManagementAPI)
    server.service = service
    result = await server.call(registered, {})
    expected = {
        "ok": False, "error_code": "custom_commands.command_name_alias_already_exists",
        "error_params": {"name": "synthetic"},
    }
    assert result == (expected if passthrough else {
        "ok": False, "error_code": "management_api.operation_rejected_check_input_profile_storage",
        "error_params": {},
    })
    if not asynchronous:
        monkeypatch.setitem(webview_host.DESKTOP_OPERATIONS, registered.name, registered)
        assert WebUIBridge.call(cast(WebUIBridge, service), registered.name, {}) == expected


def test_tray_text_has_every_label_in_every_language() -> None:
    keys = TRAY_TEXT["en"].keys()
    for language in ("uk", "ru"):
        assert TRAY_TEXT[language].keys() == keys
        for key in keys:
            assert PLACEHOLDER.findall(TRAY_TEXT[language][key]) == PLACEHOLDER.findall(TRAY_TEXT["en"][key])
    assert tray_text("xx", "open") == TRAY_TEXT["en"]["open"]


@pytest.mark.parametrize("language,running,connection,label", [
    ("en", True, "connected", "connected"),
    ("uk", True, "connected", "connected"),
    ("ru", True, "reconnecting", "reconnecting"),
    ("ru", False, "stopped", "stopped"),
    ("en", False, "failed", "failed"),
    ("uk", False, None, "stopped"),
])
def test_tray_status_uses_the_localized_connection_state(language, running, connection, label):
    status = {"running": running, "twitch_connection_state": connection, "channel": "synthetic"} if connection else None
    text = tray_status_text(language, status)
    key = "status_connected_channel" if label == "connected" else f"status_{label}"
    assert text == tray_text(language, key, channel="synthetic")


def test_tray_menu_follows_language_status_and_update():
    state = {"language": "ru", "running": True, "update": False}
    opened = []
    tray = SystemTray(
        on_open=lambda: None, on_toggle_bot=lambda: None, on_exit=lambda: None,
        is_bot_running=lambda: state["running"], language=lambda: state["language"],
        status=lambda: {"running": True, "twitch_connection_state": "connected", "channel": "synthetic"},
        update_available=lambda: state["update"], on_open_update=lambda: opened.append("update"),
    )
    assert tray._status_label(None) == tray_text("ru", "status_connected_channel", channel="synthetic")
    assert tray._open_label(None) == tray_text("ru", "open")
    assert tray._exit_label(None) == tray_text("ru", "exit")
    assert tray._toggle_label(None) == tray_text("ru", "stop")
    assert not tray._show_update(None)
    state.update(language="uk", update=True, running=False)
    assert tray._show_update(None)
    assert tray._update_label(None) == tray_text("uk", "update")
    assert tray._toggle_label(None) == tray_text("uk", "start")
    tray._handle_update(None, None)
    assert opened == ["update"]
    state["language"] = "de"
    assert tray._open_label(None) == tray_text("en", "open")


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
        close=lambda: None,
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
        assert rejected["error_code"] == "app_settings.choose_english_ukrainian_russian"
        assert store.snapshot().interface.language == "ru"
    finally:
        controller._tray_refresh_stop.set()


def test_update_item_follows_the_last_update_check(tmp_path) -> None:
    controller, bridge, tray, _, _ = _controller(tmp_path)
    assert controller.update_available() is False
    bridge._update_available = True
    assert controller.update_available() is True
