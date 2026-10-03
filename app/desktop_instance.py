"""Platform-specific desktop single-instance guards and duplicate notices."""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DesktopAlreadyRunningError(RuntimeError):
    """Another desktop process already owns this application's local state."""


ALREADY_RUNNING_MESSAGE = (
    "Twitch Bot is already running for this user. Open its existing window."
)


@contextmanager
def desktop_instance_guard(settings_path: Path) -> Iterator[None]:
    """Keep one normal desktop process per resolved local settings path."""
    if sys.platform == "win32":
        with _windows_mutex(settings_path):
            yield
    else:
        with _posix_file_lock(settings_path):
            yield


@contextmanager
def _windows_mutex(settings_path: Path) -> Iterator[None]:
    identity = str(settings_path.resolve()).casefold().encode("utf-8")
    name = f"Global\\TwitchBotDesktop-{hashlib.sha256(identity).hexdigest()[:32]}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    create_mutex.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int

    ctypes.set_last_error(0)
    handle = create_mutex(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        raise OSError(error, "Could not establish the desktop instance guard")
    try:
        if error == 183:  # ERROR_ALREADY_EXISTS
            raise DesktopAlreadyRunningError(ALREADY_RUNNING_MESSAGE)
        yield
    finally:
        close_handle(handle)


@contextmanager
def _posix_file_lock(settings_path: Path) -> Iterator[None]:
    import fcntl

    # Keep the file; closing the descriptor releases the lock even after a crash.
    directory = settings_path.resolve().parent
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".desktop-instance.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DesktopAlreadyRunningError(ALREADY_RUNNING_MESSAGE) from error
        yield
    finally:
        os.close(descriptor)


def notify_existing_desktop(message: str) -> None:
    """Show a duplicate-launch notice for Windows double-click launches."""
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    message_box = user32.MessageBoxW
    message_box.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    message_box.restype = ctypes.c_int
    message_box(None, message, "Twitch Bot", 0x30)  # MB_ICONWARNING
