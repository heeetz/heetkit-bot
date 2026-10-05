"""Windows preflight reports missing OS runtimes before touching profile state."""

import sys
from types import SimpleNamespace

import pytest

from app import windows_runtime, webview_host


def registry(monkeypatch, *, version=None, release=394802, machine=False):
    class Handle:
        def __init__(self, hive, key, view):
            self.hive, self.key, self.view = hive, key, view

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def query(handle, name):
        if name == "Release":
            return release, 4
        expected = 2 if machine else 1
        if handle.hive == expected and (not machine or handle.view & 32):
            return version, 1
        raise FileNotFoundError()

    monkeypatch.setattr(windows_runtime.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_READ=1,
        KEY_WOW64_32KEY=32, KEY_WOW64_64KEY=64,
        OpenKey=lambda hive, key, reserved, view: Handle(hive, key, view), QueryValueEx=query,
    ))


@pytest.mark.parametrize("machine", [False, True])
def test_accepts_per_user_and_machine_evergreen_runtime(monkeypatch, machine):
    registry(monkeypatch, version="145.0.1.2", machine=machine)
    windows_runtime.ensure_windows_runtime()


@pytest.mark.parametrize("version", [None, "", "0.0.0.0", "garbage", "1.0"])
def test_missing_runtime_has_actionable_guidance(monkeypatch, version):
    registry(monkeypatch, version=version)
    with pytest.raises(windows_runtime.DesktopPrerequisiteError, match="WebView2 Evergreen Runtime"):
        windows_runtime.ensure_windows_runtime()


def test_missing_net_has_distinct_guidance(monkeypatch):
    registry(monkeypatch, version="145.0.1.2", release=0)
    with pytest.raises(windows_runtime.DesktopPrerequisiteError, match=".NET Framework"):
        windows_runtime.ensure_windows_runtime()


def test_non_windows_does_not_require_registry(monkeypatch):
    monkeypatch.setattr(windows_runtime.sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "winreg", None)
    windows_runtime.ensure_windows_runtime()


@pytest.mark.parametrize("check", [False, True])
def test_preflight_failure_precedes_profile_or_credential_loading(monkeypatch, check):
    notices = []
    monkeypatch.setattr(sys, "argv", ["HeetKit.exe"] + (["--check"] if check else []))
    def fail():
        raise windows_runtime.DesktopPrerequisiteError("Install WebView2")
    monkeypatch.setattr(webview_host, "ensure_windows_runtime", fail)
    monkeypatch.setattr(webview_host, "notify_existing_desktop", notices.append)
    monkeypatch.setattr(webview_host.RuntimePaths, "default", lambda: pytest.fail("profile loaded"))
    monkeypatch.setattr(webview_host, "load_settings_with_credentials", lambda *a: pytest.fail("credentials loaded"))
    with pytest.raises(SystemExit) as error:
        webview_host.main()
    assert error.value.code == 1
    assert notices == ([] if check else ["Install WebView2"])
