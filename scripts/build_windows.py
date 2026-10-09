"""Build a pinned Windows candidate without reading any user profile."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import urllib.request
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def run(*command: str, cwd: Path = ROOT, env=None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def copy(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(ROOT):
        raise RuntimeError(f"Missing or linked build input: {source.relative_to(ROOT)}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def stage_resources(stage: Path) -> None:
    resources = ROOT / "app/resources"
    for name in ("personalities.json", "gemini_models.json", "default_triggers.json", "icon.ico", "icon.png", "tray.png"):
        copy(resources / name, stage / "app/resources" / name)
    for name in ("blocked_words.txt", "blocked_phrases.txt", "blocked_patterns.txt"):
        copy(resources / "filters" / name, stage / "app/resources/filters" / name)
    frontend = ROOT / "frontend/dist"
    for source in frontend.rglob("*"):
        if source.is_file():
            relative = source.relative_to(frontend)
            if relative.as_posix() not in ("index.html", "icon.png") and not (
                relative.parts[0] == "assets" and source.suffix in (".js", ".css")
            ):
                raise RuntimeError(f"Unexpected frontend build output: {relative}")
            copy(source, stage / "app/resources/frontend" / relative)
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        copy(ROOT / name, stage / name)
    for source in (ROOT / "third_party_licenses").rglob("*"):
        if source.is_file():
            copy(source, stage / source.relative_to(ROOT))
    copy(ROOT / "packaging/windows/PORTABLE.txt", stage / "PORTABLE.txt")
    copy(ROOT / "packaging/windows/redistribution.json", stage / "licenses/windows-redistribution.json")


def stage_native_runtime(stage: Path, work: Path) -> None:
    """Use reviewed SDK/CPython binaries instead of interpreter or ambient variants."""
    policy = json.loads((ROOT / "packaging/windows/redistribution.json").read_text(encoding="utf-8"))
    interpreter_sqlite = Path(sys.base_prefix) / "DLLs/sqlite3.dll"
    if interpreter_sqlite.is_file():
        print(f"Interpreter SQLite source: {interpreter_sqlite}; "
              f"SHA256={hashlib.sha256(interpreter_sqlite.read_bytes()).hexdigest()}", flush=True)
    for runtime in (policy["pinned_runtime"], policy["pinned_sqlite"]):
        source = policy["distributions"][runtime["distribution"]]
        archive_path = work / f"{runtime['distribution']}.zip"
        with urllib.request.urlopen(source["url"], timeout=120) as response:
            archive_path.write_bytes(response.read())
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Pinned native archive hash mismatch: {runtime['distribution']}")
        with zipfile.ZipFile(archive_path) as archive:
            # Verify the paired CPython extension without replacing its normal collection.
            for name, entry in runtime.get("compatibility_files", {}).items():
                if hashlib.sha256(archive.read(entry["member"])).hexdigest() != policy["native_files"][name]["sha256"]:
                    raise ValueError(f"Pinned runtime compatibility hash mismatch: {name}")
            for name, entry in runtime["files"].items():
                if Path(name).name != name or not name.lower().endswith(".dll"):
                    raise ValueError(f"Invalid pinned runtime filename: {name}")
                data = archive.read(entry["member"])
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError(f"Pinned runtime binary hash mismatch: {name}")
                target = stage / "native-runtime" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                if name == "sqlite3.dll":
                    print(f"Pinned SQLite source: {source['url']}#{entry['member']}; SHA256={entry['sha256']}", flush=True)


def main() -> None:
    if sys.platform != "win32" or sysconfig.get_platform() != "win-amd64" or sys.version_info[:3] != (3, 14, 7):
        raise SystemExit("Build requires Windows x64 CPython 3.14.7; target users need no Python.")
    sys.path.insert(0, str(ROOT))
    from app.version import VERSION

    output = ROOT / "dist" / f"HeetKit-{VERSION}-windows-x64.zip"
    if output.exists():
        raise SystemExit(f"Candidate already exists; move it aside before rebuilding: {output}")
    npm = shutil.which("npm.cmd")
    if npm is None:
        raise SystemExit("Build requires Node.js/npm; target users need neither.")
    work = ROOT / "build/windows" / uuid.uuid4().hex
    work.mkdir(parents=True)
    builder = work / "venv/Scripts/python.exe"
    run(sys.executable, "-m", "venv", str(work / "venv"))
    run(str(builder), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / "packaging/windows/requirements.txt"))
    run(npm, "ci", cwd=ROOT / "frontend")
    run(npm, "run", "build", cwd=ROOT / "frontend")
    stage = work / "stage"
    stage_resources(stage)
    # Installed package licenses plus Python's own full license collection.
    run(str(builder), str(ROOT / "scripts/windows_build_licenses.py"), str(stage))
    stage_native_runtime(stage, work)
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith(("HEETKIT_", "TWITCH_", "GEMINI_")) or name in ("DATABASE_URL", "PYTHONPATH", "PYTHONHOME"):
            environment.pop(name)
    environment.update(HEETKIT_BUILD_STAGE=str(stage), HEETKIT_BUILD_VERSION=VERSION)
    # Dependency discovery must not select DLLs from unrelated tools on PATH.
    windows = Path(os.environ["SystemRoot"])
    environment["PATH"] = os.pathsep.join(str(path) for path in (
        builder.parent, Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs",
        windows / "System32", windows,
    ))
    run(str(builder), "-m", "PyInstaller", "--noconfirm", "--distpath", str(work / "dist"),
        "--workpath", str(work / "freeze"), str(ROOT / "packaging/windows/HeetKit.spec"), env=environment)
    bundle = work / "dist/HeetKit"
    run(str(builder), str(ROOT / "scripts/inspect_windows_bundle.py"), str(bundle))
    run(str(builder), "-I", str(ROOT / "scripts/check_windows_sqlite.py"), str(bundle))
    files = [{"path": p.relative_to(bundle).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(bundle.rglob("*")) if p.is_file()]
    (bundle / "BUILD-MANIFEST.json").write_text(json.dumps({"version": VERSION, "python": "3.14.7", "files": files}, indent=2) + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.write(path, Path("HeetKit") / path.relative_to(bundle))
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{checksum}  {output.name}\n", encoding="ascii")
    print(f"Version: {VERSION}\nBundle: {bundle}\nPortable ZIP: {output}\nSHA-256: {checksum}")


if __name__ == "__main__":
    main()
