"""System tray adapter for the Windows desktop host."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any


class SystemTray:
    def __init__(
        self,
        *,
        on_open: Callable[[], None],
        on_toggle_bot: Callable[[], None],
        on_exit: Callable[[], None],
        is_bot_running: Callable[[], bool],
    ) -> None:
        self._on_open = on_open
        self._on_toggle_bot = on_toggle_bot
        self._on_exit = on_exit
        self._is_bot_running = is_bot_running
        self._lock = RLock()
        self._icon: Any | None = None

    def start(self) -> None:
        with self._lock:
            if self._icon is not None:
                return
            import pystray
            from PIL import Image, ImageDraw

            image = Image.new("RGBA", (64, 64), (11, 15, 23, 255))
            drawing = ImageDraw.Draw(image)
            drawing.rounded_rectangle((6, 6, 58, 58), 13, fill=(124, 77, 255, 255))
            drawing.rectangle((19, 18, 45, 26), fill=(255, 255, 255, 255))
            drawing.rectangle((28, 24, 36, 47), fill=(255, 255, 255, 255))

            icon = pystray.Icon(
                "twitch-bot",
                image,
                "Twitch Bot",
                menu=pystray.Menu(
                    pystray.MenuItem("Open", self._handle_open, default=True),
                    pystray.MenuItem(self._toggle_label, self._handle_toggle),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit", self._handle_exit),
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

    def _toggle_label(self, item: Any) -> str:
        try:
            return "Stop Bot" if self._is_bot_running() else "Start Bot"
        except Exception:
            return "Start / Stop Bot"

    def _handle_open(self, icon: Any, item: Any) -> None:
        self._on_open()

    def _handle_toggle(self, icon: Any, item: Any) -> None:
        self._on_toggle_bot()

    def _handle_exit(self, icon: Any, item: Any) -> None:
        self._on_exit()
