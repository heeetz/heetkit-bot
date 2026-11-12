"""Hand off Desktop exit, optional installation, and one monitored relaunch."""

from __future__ import annotations

import ctypes
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time

from app.desktop_instance import DesktopAlreadyRunningError, desktop_instance_guard, notify_existing_desktop
from app.runtime_paths import RuntimePaths, _backup_sqlite_if_missing, _is_link
from app.services.updates import (
    ReleaseAssets, UpdateCheckError, VerifiedUpdate, publisher_key, verify_installer_file, verify_manifest,
)
from app.version import VERSION, is_prerelease, windows_version

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{C2D78D77-6F6E-4B63-9E60-871E7B955961}_is1"
WORKER_FLAG = "--desktop-relaunch-worker"
READY_FLAG = "--desktop-relaunch-ready"
REBOOT_REQUIRED = {8, 3010}


def installed_directory(executable: Path | None = None) -> Path | None:
    if executable is None:
        if sys.platform != "win32" or not getattr(sys, "frozen", False) or struct.calcsize("P") != 8:
            return None
        executable = Path(sys.executable)
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            location = Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve(strict=True)
            uninstall = Path(winreg.QueryValueEx(key, "UninstallString")[0].strip('"'))
        return location if (
            executable.name.casefold() == "heetkit.exe" and executable.resolve(strict=True) == location / "HeetKit.exe"
            and uninstall.parent.resolve() == location and uninstall.name.lower().startswith("unins")
            and uninstall.suffix.lower() == ".exe" and uninstall.is_file()
        ) else None
    except (OSError, TypeError, ValueError):
        return None


def work_root() -> Path:
    # LOCALAPPDATA inherits the current user's private Windows ACL. POSIX
    # source restarts use a 0700 mkdtemp directory under the system temp root.
    return Path(os.environ["LOCALAPPDATA"]) / "HeetKit Update Work"


def _overlap(left: Path, right: Path) -> bool:
    left, right = left.resolve(), right.resolve()
    return left.is_relative_to(right) or right.is_relative_to(left)


def new_work_directory(profile: Path, install: Path | None = None) -> Path:
    if install is None:
        return Path(tempfile.mkdtemp(prefix="heetkit-restart-"))
    root = work_root()
    if _is_link(root) or _overlap(profile, root) or _overlap(install, root) or _overlap(install, profile):
        raise UpdateCheckError("The installation, profile and update workspace must use separate directories.")
    root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="upgrade-", dir=root))


@contextmanager
def installation_access(directory: Path, *, exclusive: bool = False):
    """Hold a shared handle during normal use or an exclusive handle during replacement."""
    root = work_root()
    if _is_link(root):
        raise OSError("The update workspace is linked.")
    root.mkdir(exist_ok=True)
    identity = hashlib.sha256(str(directory.resolve()).casefold().encode()).hexdigest()[:32]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                       ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
    create.restype = ctypes.c_void_p
    handle = create(str(root / f"{identity}.lock"), 0x80000000, 0 if exclusive else 1, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error == 32:
            raise DesktopAlreadyRunningError("Close every HeetKit window using this installation and retry after any update finishes.")
        raise ctypes.WinError(error)
    try:
        yield
    finally:
        _close_handle(kernel, handle)


def _close_handle(kernel, handle) -> None:
    close = kernel.CloseHandle
    close.argtypes = (ctypes.c_void_p,)
    close(handle)


def _await_parent(stage: Path, pid: int) -> None:
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel.OpenProcess
        open_process.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        open_process.restype = ctypes.c_void_p
        handle = open_process(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            wait = kernel.WaitForSingleObject
            wait.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            wait.restype = ctypes.c_uint32
            (stage / "worker-ready").touch()
            if wait(handle, 90_000) != 0:
                raise OSError("HeetKit did not exit in time.")
        finally:
            _close_handle(kernel, handle)
    else:
        if os.getppid() != pid:
            raise OSError("The original Desktop process has already exited.")
        (stage / "worker-ready").touch()
        deadline = time.monotonic() + 90
        while os.getppid() == pid:
            if time.monotonic() >= deadline:
                raise OSError("HeetKit did not exit in time.")
            time.sleep(0.1)


def _desktop_command(executable: Path) -> list[str]:
    return [str(executable)] if getattr(sys, "frozen", False) else [str(executable), "-m", "app.main"]


def _launch(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.Popen:
    environment = os.environ.copy() if env is None else env.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return subprocess.Popen(command, cwd=cwd, env=environment)


def _wait_for_file(path: Path, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not path.is_file():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise OSError("The Desktop process did not report readiness.")
        time.sleep(0.05)


def prepare_worker_copy(stage: Path, install: Path) -> Path:
    runner = stage / "runner"
    runner.mkdir()
    # Copy the existing onedir runtime so no executable, DLL or resource in
    # the registered install is held open by the updater itself.
    for name in ("HeetKit.exe", "HeetKit.exe.config"):
        shutil.copy2(install / name, runner / name)
    shutil.copytree(install / "_internal", runner / "_internal")
    return runner / "HeetKit.exe"


def start_worker(stage: Path, profile: Path, running: bool, *, dev_url: str | None = None,
                 install: Path | None = None, update: VerifiedUpdate | None = None) -> None:
    executable = Path(sys.executable).resolve()
    options = {
        "profile": str(profile), "running": running, "dev_url": dev_url,
        "executable": str(executable), "cwd": str(Path.cwd()),
    }
    worker = executable
    if install is not None and update is not None:
        options["update"] = {
            "version": update.assets.version, "tag": update.assets.tag,
            "size": update.assets.size, "digest": update.assets.digest,
        }
        (stage / "release.manifest.json").write_bytes(update.manifest)
        (stage / "release.manifest.sig").write_bytes(update.signature)
        worker = stage / "runner" / "HeetKit.exe"
    (stage / "request.json").write_text(json.dumps(options), encoding="utf-8")
    process = _launch([*_desktop_command(worker), WORKER_FLAG, str(stage), str(os.getpid())],
                      cwd=worker.parent if getattr(sys, "frozen", False) else Path.cwd())
    try:
        _wait_for_file(stage / "worker-ready", process, 20)
    except OSError:
        process.kill()
        process.wait()
        raise


def backup_profile(profile: RuntimePaths, stage: Path) -> None:
    snapshot = stage / "profile-backup"
    temporary = stage / "profile-backup.partial"
    databases = (profile.database, profile.database.with_name(profile.database.name + ".analytics.sqlite3"))
    sidecars = {db.with_name(db.name + suffix) for db in databases for suffix in ("-wal", "-shm", "-journal")}

    def copy(source: Path, target: Path) -> None:
        if _is_link(source):
            raise OSError("The profile contains a linked file or directory.")
        if source in sidecars:
            return
        if source.is_dir():
            target.mkdir()
            for entry in source.iterdir():
                copy(entry, target / entry.name)
        elif source in databases and source.is_file():
            _backup_sqlite_if_missing(source, target)
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            raise OSError("The profile contains an unsupported file.")

    with ExitStack() as guards:
        guards.enter_context(desktop_instance_guard(profile.app_settings))
        for database in databases:
            guards.enter_context(desktop_instance_guard(database, database=True))
        copy(profile.root, temporary)
        temporary.rename(snapshot)


def _run_installer(installer: Path, install: Path, log: Path, profile: Path) -> int:
    environment = os.environ | {"HEETKIT_DATA_DIR": str(profile)}
    set_dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
    set_dll_directory.argtypes = (ctypes.c_wchar_p,)
    set_dll_directory(None)  # Let Inno use its own Windows DLL search path.
    try:
        return subprocess.run(
            [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-", "/NORESTART",
             "/RESTARTEXITCODE=3010", "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS",
             f"/DIR={install}", f"/LOG={log}"],
            cwd=installer.parent, env=environment, check=False,
        ).returncode
    finally:
        set_dll_directory(getattr(sys, "_MEIPASS", None))


def _file_version(executable: Path) -> tuple[int, int, int, int]:
    api = ctypes.windll.version
    size_of_version = api.GetFileVersionInfoSizeW
    size_of_version.argtypes = (ctypes.c_wchar_p, ctypes.c_void_p)
    size_of_version.restype = ctypes.c_uint32
    read_version = api.GetFileVersionInfoW
    read_version.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
    query = api.VerQueryValueW
    query.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p)
    size = size_of_version(str(executable), None)
    buffer = ctypes.create_string_buffer(size)
    pointer = ctypes.POINTER(ctypes.c_uint32)()
    length = ctypes.c_uint32()
    if (not size or not read_version(str(executable), 0, size, buffer)
            or not query(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length))
            or length.value < 16 or pointer[0] != 0xFEEF04BD):
        raise UpdateCheckError("Windows could not read the executable version metadata.")
    high, low = pointer[2], pointer[3]
    return high >> 16, high & 0xFFFF, low >> 16, low & 0xFFFF


def verify_installer_version(installer: Path, version: str) -> None:
    if _file_version(installer) != windows_version(version):
        raise UpdateCheckError("The installer executable version does not match the signed release.")


def _install(stage: Path, executable: Path, profile: Path, assets: ReleaseAssets) -> None:
    key = publisher_key()
    install = installed_directory(executable)
    if key is None or install is None or _overlap(install, profile):
        raise UpdateCheckError("The registered installation or publisher key is unavailable.")
    if is_prerelease(assets.version) or windows_version(assets.version) <= windows_version(VERSION):
        raise UpdateCheckError("The selected installer must be a newer stable version.")
    verified = verify_manifest(assets, (stage / "release.manifest.json").read_bytes(),
                               (stage / "release.manifest.sig").read_bytes(), key)
    installer = stage / assets.name
    with installation_access(install, exclusive=True):
        verify_installer_file(installer, verified)
        verify_installer_version(installer, assets.version)
        backup_profile(RuntimePaths(profile), stage)
        (stage / "backup-versions.json").write_text(
            json.dumps({"previous_version": VERSION, "target_version": assets.version}), encoding="utf-8",
        )
        code = _run_installer(installer, install, stage / "installer.log", profile)
        if code == 0 and _file_version(executable) != windows_version(assets.version):
            raise UpdateCheckError("Setup did not install the intended version. Reinstall it from GitHub Releases before reopening HeetKit.")
    if code in REBOOT_REQUIRED:
        raise UpdateCheckError("Windows needs a restart to complete the update. Restart Windows when ready, then open HeetKit from Start.")
    if code != 0:
        raise UpdateCheckError(f"HeetKit Setup failed (exit code {code}). Close other HeetKit copies and retry with the installer from GitHub Releases.")


def _relaunch(options: dict, stage: Path, version: str) -> None:
    executable = Path(options["executable"])
    ready = stage / "desktop-ready"
    command = [*_desktop_command(executable), "--data-dir", options["profile"],
               "--resume-bot" if options["running"] else "--stopped", READY_FLAG, str(ready)]
    if options["dev_url"]:
        command.extend(("--dev-url", options["dev_url"]))
    cwd = executable.parent if getattr(sys, "frozen", False) else Path(options["cwd"])
    process = _launch(command, cwd=cwd)
    _wait_for_file(ready, process, 60)
    if ready.read_text(encoding="utf-8") != version:
        raise OSError("The reopened Desktop reported an unexpected version.")


def run_worker(stage: Path, parent_pid: int) -> None:
    installer: Path | None = None
    updating = False
    try:
        options = json.loads((stage / "request.json").read_text(encoding="utf-8"))
        updating = "update" in options
        _await_parent(stage, parent_pid)
        if not (stage / "shutdown-complete").is_file():
            raise UpdateCheckError("HeetKit did not finish shutting down. Open it from Start and check Logs before retrying.")
        version = VERSION
        if updating:
            assets = ReleaseAssets(**options["update"])
            installer = stage / assets.name
            _install(stage, Path(options["executable"]), Path(options["profile"]), assets)
            version = assets.version
        try:
            _relaunch(options, stage, version)
        except OSError as error:
            raise UpdateCheckError(f"HeetKit {version} did not confirm startup. Check any open HeetKit window, then try opening it from Start. For an update, reinstall the intended version if needed.") from error
    except (OSError, ValueError, sqlite3.Error, DesktopAlreadyRunningError, UpdateCheckError) as error:
        message = str(error) if isinstance(error, (DesktopAlreadyRunningError, UpdateCheckError)) else (
            "The Desktop handoff could not finish. Check available disk space and permissions, then open HeetKit or reinstall from GitHub Releases."
        )
        if updating:
            log = stage / "installer.log"
            if log.is_file():
                message += f"\n\nInstaller log: {log}"
            if (stage / "profile-backup").is_dir():
                message += f"\n\nPre-update profile backup: {stage / 'profile-backup'}"
        if sys.platform == "win32":
            notify_existing_desktop(message)
        else:
            print(message, file=sys.stderr)
    finally:
        if updating:
            try:
                if installer is not None:
                    installer.unlink(missing_ok=True)
            except OSError:
                pass
            (stage / "worker-finished").touch()
        else:
            shutil.rmtree(stage, ignore_errors=True)


def report_desktop_ready(path: Path) -> None:
    if path.name != "desktop-ready" or not (path.parent / "worker-ready").is_file():
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text(VERSION, encoding="utf-8")
    temporary.replace(path)


def remove_finished_runners() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    root = work_root()
    if _is_link(root):
        return
    for stage in root.glob("upgrade-*"):
        runner = stage / "runner"
        if not _is_link(stage) and not _is_link(runner) and (stage / "worker-finished").is_file():
            shutil.rmtree(runner, ignore_errors=True)
