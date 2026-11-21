"""System tray adapter for the Windows desktop host."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock
from typing import Any

# Tray menu text follows the UI language chosen in Settings (task 2.2).
TRAY_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "open": "Open",
        "start": "Start Bot",
        "stop": "Stop Bot",
        "toggle": "Start / Stop Bot",
        "update": "Update available",
        "exit": "Exit",
        "status_stopped": "Stopped",
        "status_connecting": "Connecting…",
        "status_connected": "Connected",
        "status_connected_channel": "Connected · #{channel}",
        "status_reconnecting": "Reconnecting…",
        "status_auth_required": "Sign-in required",
        "status_failed": "Connection failed",
    },
    "uk": {
        "open": "Відкрити",
        "start": "Запустити бота",
        "stop": "Зупинити бота",
        "toggle": "Запустити / зупинити бота",
        "update": "Доступне оновлення",
        "exit": "Вийти",
        "status_stopped": "Зупинено",
        "status_connecting": "Підключення…",
        "status_connected": "Підключено",
        "status_connected_channel": "Підключено · #{channel}",
        "status_reconnecting": "Перепідключення…",
        "status_auth_required": "Потрібен вхід у Twitch",
        "status_failed": "Не вдалося підключитися",
    },
    "ru": {
        "open": "Открыть",
        "start": "Запустить бота",
        "stop": "Остановить бота",
        "toggle": "Запустить / остановить бота",
        "update": "Доступно обновление",
        "exit": "Выйти",
        "status_stopped": "Остановлен",
        "status_connecting": "Подключение…",
        "status_connected": "Подключено",
        "status_connected_channel": "Подключено · #{channel}",
        "status_reconnecting": "Переподключение…",
        "status_auth_required": "Нужен вход в Twitch",
        "status_failed": "Не удалось подключиться",
    },
}


def tray_text(language: str, key: str, **params: str) -> str:
    catalog = TRAY_TEXT.get(language, TRAY_TEXT["en"])
    template = catalog.get(key, TRAY_TEXT["en"][key])
    return template.format(**params) if params else template


def tray_status_text(language: str, status: Mapping[str, object] | None) -> str:
    """One disabled status line: "Connected · #channel", "Stopped", "Reconnecting…"."""
    if not status or not status.get("running"):
        state = status.get("twitch_connection_state") if status else None
        return tray_text(language, "status_auth_required" if state == "auth_required"
                         else "status_failed" if state == "failed" else "status_stopped")
    state = status.get("twitch_connection_state")
    if state == "connected":
        channel = status.get("channel")
        if isinstance(channel, str) and channel.strip():
            return tray_text(language, "status_connected_channel", channel=channel.strip().removeprefix("#"))
        return tray_text(language, "status_connected")
    if state in ("reconnecting", "auth_required", "failed", "connecting"):
        return tray_text(language, f"status_{state}")
    return tray_text(language, "status_connecting")


class SystemTray:
    def __init__(
        self,
        *,
        on_open: Callable[[], None],
        on_toggle_bot: Callable[[], None],
        on_exit: Callable[[], None],
        is_bot_running: Callable[[], bool],
        language: Callable[[], str] = lambda: "en",
        status: Callable[[], Mapping[str, object] | None] = lambda: None,
        update_available: Callable[[], bool] = lambda: False,
        on_open_update: Callable[[], None] | None = None,
    ) -> None:
        self._on_open = on_open
        self._on_toggle_bot = on_toggle_bot
        self._on_exit = on_exit
        self._is_bot_running = is_bot_running
        self._language = language
        self._status = status
        self._update_available = update_available
        self._on_open_update = on_open_update or on_open
        self._lock = RLock()
        self._icon: Any | None = None

    def start(self) -> None:
        with self._lock:
            if self._icon is not None:
                return
            import pystray
            from PIL import Image

            with Image.open(Path(__file__).resolve().parent / "resources" / "tray.png") as source:
                image = source.copy()

            icon = pystray.Icon(
                "heetkit",
                image,
                "HeetKit",
                menu=pystray.Menu(
                    pystray.MenuItem(self._status_label, None, enabled=False),
                    pystray.MenuItem(self._update_label, self._handle_update, visible=self._show_update),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(self._open_label, self._handle_open, default=True),
                    pystray.MenuItem(self._toggle_label, self._handle_toggle),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(self._exit_label, self._handle_exit),
                ),
            )
            try:
                icon.run_detached()
            except Exception:
                icon.stop()
                raise
            self._icon = icon

    def stop(self) -> None:
        with self._lock:
            icon = self._icon
            self._icon = None
        if icon is not None:
            icon.stop()

    def update_menu(self) -> None:
        with self._lock:
            icon = self._icon
        if icon is not None:
            icon.update_menu()

    def _current_language(self) -> str:
        try:
            language = self._language()
        except Exception:
            return "en"
        return language if language in TRAY_TEXT else "en"

    def _status_label(self, item: Any) -> str:
        language = self._current_language()
        try:
            status = self._status()
        except Exception:
            status = None
        return tray_status_text(language, status)

    def _show_update(self, item: Any) -> bool:
        try:
            return bool(self._update_available())
        except Exception:
            return False

    def _update_label(self, item: Any) -> str:
        return tray_text(self._current_language(), "update")

    def _open_label(self, item: Any) -> str:
        return tray_text(self._current_language(), "open")

    def _exit_label(self, item: Any) -> str:
        return tray_text(self._current_language(), "exit")

    def _toggle_label(self, item: Any) -> str:
        language = self._current_language()
        try:
            return tray_text(language, "stop" if self._is_bot_running() else "start")
        except Exception:
            return tray_text(language, "toggle")

    def _handle_open(self, icon: Any, item: Any) -> None:
        self._on_open()

    def _handle_update(self, icon: Any, item: Any) -> None:
        self._on_open_update()

    def _handle_toggle(self, icon: Any, item: Any) -> None:
        self._on_toggle_bot()

    def _handle_exit(self, icon: Any, item: Any) -> None:
        self._on_exit()
