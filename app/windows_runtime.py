"""Check the desktop renderer prerequisites before loading a Windows profile."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys


WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
_EDGE_CLIENT_KEY = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_NET_KEY = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"


class DesktopPrerequisiteError(RuntimeError):
    """A required Windows desktop runtime is missing or cannot be loaded."""


_UNBLOCK_GUIDANCE = (
    "If you trust the HeetKit ZIP, right-click the ZIP, choose Properties, "
    "tick Unblock if shown, then Apply and extract into a new folder. "
    "Unblocking the ZIP does not repair files already extracted. "
    "See _internal/PORTABLE.txt for instructions for an existing folder."
)


def _ensure_renderer_loads() -> None:
    # Downloaded ZIPs can propagate Mark of the Web to managed DLLs. Report this
    # before CLR's native loader hides the FileLoadException behind a NULL result.
    if getattr(sys, "frozen", False):
        internal = Path(sys._MEIPASS)
        for directory in (internal / "pythonnet/runtime", internal / "webview/lib"):
            for dll in directory.rglob("*.dll"):
                try:
                    zone = Path(f"{dll}:Zone.Identifier").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if any(line.strip() in ("ZoneId=3", "ZoneId=4") for line in zone.splitlines()):
                    raise DesktopPrerequisiteError(
                        f"Windows has marked a HeetKit DLL as downloaded: {dll.name}. "
                        + _UNBLOCK_GUIDANCE
                    )
    try:
        importlib.import_module("clr")
        importlib.import_module("webview.platforms.edgechromium")
    except Exception as error:
        raise DesktopPrerequisiteError(
            "HeetKit could not load its .NET/WebView2 desktop libraries. "
            + _UNBLOCK_GUIDANCE
            + " If the files are unblocked, verify the complete ZIP was extracted and "
            "repair the Microsoft .NET Framework/WebView2 installations. "
            f"Loader detail: {error}"
        ) from error


def ensure_windows_runtime() -> None:
    if sys.platform != "win32":
        return
    import winreg

    def read_value(hive: int, key: str, value: str, view: int = 0):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                return winreg.QueryValueEx(handle, value)[0]
        except OSError:
            return None

    release = read_value(winreg.HKEY_LOCAL_MACHINE, _NET_KEY, "Release", winreg.KEY_WOW64_64KEY)
    if not isinstance(release, int) or release < 394802:
        raise DesktopPrerequisiteError(
            "HeetKit requires Microsoft .NET Framework 4.6.2 or newer. "
            "Install the current .NET Framework from Microsoft, then reopen HeetKit."
        )
    for hive, view in (
        (winreg.HKEY_CURRENT_USER, 0),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
    ):
        version = read_value(hive, _EDGE_CLIENT_KEY, "pv", view)
        if isinstance(version, str):
            parts = version.split(".")
            if len(parts) == 4 and all(part.isdecimal() for part in parts) and any(int(part) for part in parts):
                _ensure_renderer_loads()
                return
    raise DesktopPrerequisiteError(
        "HeetKit requires Microsoft Edge WebView2 Evergreen Runtime. "
        f"Install it from {WEBVIEW2_DOWNLOAD_URL}, then reopen HeetKit."
    )
