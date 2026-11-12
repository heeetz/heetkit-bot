"""Synthetic release, installer, and process boundaries for Desktop updates."""

import asyncio
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from app import desktop_relaunch as relaunch
from app.runtime_paths import RuntimePaths
from app.services import updates
from app.version import windows_version
from app.webview_host import WebUIBridge


INSTALLER = b"synthetic installer contents"


@pytest.fixture
def signed_release():
    key = Ed25519PrivateKey.generate()
    digest = hashlib.sha256(INSTALLER).hexdigest()
    assets = updates.ReleaseAssets("2.0.0", "v2.0.0", len(INSTALLER), "sha256:" + digest)
    manifest = json.dumps({"version": assets.version, "asset": assets.name,
                           "size": assets.size, "sha256": digest}).encode()
    return assets, manifest, key.sign(manifest), key.public_key().public_bytes_raw()


def test_exact_stable_assets_only(signed_release):
    assets, _, _, _ = signed_release
    files = [{"name": assets.name + suffix, "state": "uploaded", "browser_download_url": assets.url(suffix),
              "size": assets.size, "digest": assets.digest} for suffix in ("", ".manifest.json", ".manifest.sig")]
    release = {"tag_name": assets.tag, "assets": files + [{"name": "HeetKit-2.0.0-windows-x64.zip"}]}
    assert updates.select_installer(release, assets.version) == assets
    assert updates.select_installer(release, "2.0.1") is None
    assert updates.select_installer({**release, "assets": files + files[:1]}, assets.version) is None
    assert updates.select_installer({**release, "assets": files[:-1]}, assets.version) is None
    files[0]["browser_download_url"] = "https://another.example/setup.exe"
    assert updates.select_installer(release, assets.version) is None


async def test_release_verifies_the_publisher_and_manifest_binding(signed_release):
    assets, manifest, signature, key = signed_release
    files = {assets.url(".manifest.json"): manifest, assets.url(".manifest.sig"): signature}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=files[str(request.url)]))) as client:
        verified = await updates.authorize_installer(client, assets, key)
        assert verified.sha256 == assets.digest.removeprefix("sha256:")
        files[assets.url(".manifest.sig")] = b"?" * 64
        with pytest.raises(updates.UpdateCheckError, match="publisher verification"):
            await updates.authorize_installer(client, assets, key)

    private_key = Ed25519PrivateKey.generate()
    different_version = manifest.replace(b"2.0.0", b"2.0.1")
    with pytest.raises(updates.UpdateCheckError, match="does not match"):
        updates.verify_manifest(assets, different_version, private_key.sign(different_version),
                                private_key.public_key().public_bytes_raw())


@pytest.mark.parametrize("case", ["ok", "hash", "short", "large", "interrupt", "redirect"])
async def test_download_progress_and_verification(tmp_path, signed_release, case):
    verified = updates.verify_manifest(*signed_release)
    progress = []

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"synthetic"
            raise httpx.ReadError("disconnected")

    def handler(request):
        if case == "interrupt":
            return httpx.Response(200, stream=Interrupted())
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://untrusted.example/setup.exe"})
        content = {
            "ok": INSTALLER, "hash": b"?" * len(INSTALLER), "short": INSTALLER[:-1], "large": INSTALLER + b"?",
        }[case]
        return httpx.Response(200, content=content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path = tmp_path / verified.assets.name
        if case == "ok":
            await updates.download_installer(client, verified, path, lambda *data: progress.append(data))
            assert path.read_bytes() == INSTALLER
            assert progress == [("downloading", 0), ("downloading", len(INSTALLER)), ("verifying", len(INSTALLER))]
        else:
            with pytest.raises(updates.UpdateCheckError):
                await updates.download_installer(client, verified, path, lambda *data: progress.append(data))


def test_portable_has_no_automatic_update_and_overlapping_requests_are_rejected(monkeypatch):
    async def check(client, current):
        return {"latest_version": "2.0.0", "update_available": True}

    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(http_client=None)))
    bridge._controller = SimpleNamespace()
    bridge._wait_for_backend = lambda coroutine, **kwargs: asyncio.run(coroutine)
    monkeypatch.setattr("app.webview_host.check_for_updates", check)
    monkeypatch.setattr(relaunch, "installed_directory", lambda: None)
    result = bridge.check_for_updates()
    assert result["automatic_update"] is False
    assert "portable" in result["automatic_update_reason"]
    assert not bridge.prepare_desktop_update("2.0.0")["ok"]
    with bridge._desktop_operation:
        assert not bridge.prepare_desktop_update("2.0.0")["ok"]
        assert not bridge.finish_desktop_update("2.0.0")["ok"]


def test_install_registration_belongs_to_the_running_copy(tmp_path, monkeypatch):
    install = tmp_path / "Custom Install With Spaces"
    install.mkdir()
    installed_exe = install / "HeetKit.exe"
    uninstaller = install / "unins000.exe"
    portable = tmp_path / "HeetKit.exe"
    for path in (installed_exe, uninstaller, portable):
        path.touch()
    registration = {"InstallLocation": str(install), "UninstallString": f'"{uninstaller}"'}
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_CURRENT_USER=1, KEY_READ=2, KEY_WOW64_64KEY=4,
        OpenKey=lambda *args: nullcontext(), QueryValueEx=lambda key, name: (registration[name], 1),
    ))
    assert relaunch.installed_directory(installed_exe) == install
    assert relaunch.installed_directory(portable) is None
    uninstaller.unlink()
    assert relaunch.installed_directory(installed_exe) is None


@pytest.mark.parametrize("code", [0, 5, 8, 3010])
def test_worker_relaunches_once_only_after_success(tmp_path, monkeypatch, signed_release, code):
    assets, manifest, signature, key = signed_release
    install = tmp_path / "Custom Install With Spaces"
    profile = tmp_path / "Private Test Profile"
    stage = tmp_path / "work"
    stage.mkdir()
    installer = stage / assets.name
    installer.write_bytes(INSTALLER)
    (stage / "release.manifest.json").write_bytes(manifest)
    (stage / "release.manifest.sig").write_bytes(signature)
    (stage / "shutdown-complete").touch()
    (stage / "request.json").write_text(json.dumps({
        "executable": str(install / "HeetKit.exe"), "profile": str(profile), "running": True,
        "update": vars(assets),
    }), encoding="utf-8")
    calls = []
    messages = []
    monkeypatch.setattr(relaunch.sys, "platform", "win32")
    monkeypatch.setattr(relaunch, "publisher_key", lambda: key)
    monkeypatch.setattr(relaunch, "installed_directory", lambda executable: install)
    monkeypatch.setattr(relaunch, "_await_parent", lambda *args: calls.append("exit"))
    monkeypatch.setattr(relaunch, "_file_version", lambda *args: windows_version(assets.version))
    monkeypatch.setattr(relaunch, "installation_access", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(relaunch, "backup_profile", lambda *args: calls.append("backup"))
    monkeypatch.setattr(relaunch, "notify_existing_desktop", messages.append)
    monkeypatch.setattr(relaunch, "_relaunch", lambda options, path, version: calls.append(("relaunch", version)))

    def run(path, directory, log, selected_profile):
        assert (path, directory, selected_profile) == (installer, install, profile)
        log.write_text("synthetic log", encoding="utf-8")
        calls.append("install")
        return code

    monkeypatch.setattr(relaunch, "_run_installer", run)
    relaunch.run_worker(stage, 1234)
    assert calls == ["exit", "backup", "install"] + ([("relaunch", assets.version)] if code == 0 else [])
    assert (stage / "installer.log").is_file()
    assert not installer.exists()
    if code:
        assert "Installer log:" in messages[0]
        assert ("restart" in messages[0]) == (code in {8, 3010})
    else:
        assert not messages


@pytest.mark.parametrize("running", [False, True])
def test_relaunch_keeps_run_intent_and_checks_reported_version(tmp_path, monkeypatch, running):
    options = {"executable": sys.executable, "profile": str(tmp_path / "Private Test Profile"),
               "running": running, "cwd": str(tmp_path), "dev_url": None}
    calls = []
    monkeypatch.setattr(relaunch, "_launch", lambda command, **kwargs: calls.append(command))
    monkeypatch.setattr(relaunch, "_wait_for_file", lambda path, *args: path.write_text("1.0.0", encoding="utf-8"))
    with pytest.raises(OSError, match="unexpected version"):
        relaunch._relaunch(options, tmp_path, "2.0.0")
    assert len(calls) == 1
    assert ("--resume-bot" if running else "--stopped") in calls[0]
    assert options["profile"] in calls[0]


def test_profile_snapshot_captures_wal_data_and_other_profile_state(tmp_path, monkeypatch):
    profile = RuntimePaths(tmp_path / "profile")
    profile.data.mkdir(parents=True)
    profile.auth.mkdir()
    profile.tokens.write_text("synthetic token file", encoding="utf-8")
    stage = tmp_path / "work"
    stage.mkdir()
    monkeypatch.setattr(relaunch, "desktop_instance_guard", lambda *args, **kwargs: nullcontext())
    with sqlite3.connect(profile.database) as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA user_version=2")
        database.execute("CREATE TABLE test (name TEXT)")
        database.execute("INSERT INTO test VALUES ('saved row')")
        database.commit()
        relaunch.backup_profile(profile, stage)
    backup = RuntimePaths(stage / "profile-backup")
    assert backup.tokens.read_bytes() == profile.tokens.read_bytes()
    with sqlite3.connect(backup.database) as database:
        assert database.execute("SELECT name FROM test").fetchone() == ("saved row",)
        assert database.execute("PRAGMA user_version").fetchone() == (2,)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows executable version resource")
def test_read_native_executable_version():
    assert relaunch._file_version(Path(sys.executable))[:2] == sys.version_info[:2]
