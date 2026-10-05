"""Windows preflight reports missing OS runtimes before touching profile state."""

import sys
from types import SimpleNamespace

import pytest

from app import windows_runtime, webview_host


def registry(monkeypatch, *, version=None, release=394802, machine=False):
    monkeypatch.setattr(windows_runtime, "_ensure_renderer_loads", lambda: None)
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
    monkeypatch.setattr(windows_runtime, "_ensure_renderer_loads", lambda: pytest.fail("loaded Windows renderer"))
    windows_runtime.ensure_windows_runtime()


def test_preflight_loads_desktop_libraries_after_registry_checks(monkeypatch):
    registry(monkeypatch, version="145.0.1.2")
    calls = []
    monkeypatch.setattr(windows_runtime, "_ensure_renderer_loads", lambda: calls.append("renderer"))
    windows_runtime.ensure_windows_runtime()
    assert calls == ["renderer"]


@pytest.mark.parametrize("relative", ["pythonnet/runtime/Python.Runtime.dll", "webview/lib/Microsoft.Web.WebView2.Core.dll"])
def test_blocked_managed_dll_reports_unblock_without_loading_or_modifying_it(monkeypatch, tmp_path, relative):
    dll = tmp_path / relative
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"synthetic DLL")
    zone = type(dll)(f"{dll}:Zone.Identifier")
    zone.write_text("[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(windows_runtime.importlib, "import_module", lambda name: pytest.fail("loaded blocked DLL"))
    with pytest.raises(windows_runtime.DesktopPrerequisiteError, match="Windows has marked.*Unblock.*new folder"):
        windows_runtime._ensure_renderer_loads()
    assert zone.read_text(encoding="utf-8") == "[ZoneTransfer]\nZoneId=3\n"
    assert dll.read_bytes() == b"synthetic DLL"


def test_renderer_load_failure_has_actionable_details(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    def fail(name):
        raise RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize")
    monkeypatch.setattr(windows_runtime.importlib, "import_module", fail)
    with pytest.raises(windows_runtime.DesktopPrerequisiteError, match="Unblock.*Loader detail: Failed to resolve"):
        windows_runtime._ensure_renderer_loads()


def test_unblocked_bundle_checks_clr_and_webview_assemblies(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    calls = []
    monkeypatch.setattr(windows_runtime.importlib, "import_module", calls.append)
    windows_runtime._ensure_renderer_loads()
    assert calls == ["clr", "webview.platforms.edgechromium"]


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
