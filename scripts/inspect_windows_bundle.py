"""Fail packaging on development/private inputs or unwanted native architectures."""

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from PyInstaller.archive.readers import CArchiveReader

bundle = Path(sys.argv[1])
forbidden_parts = {".agent", ".agents", ".codex", ".git", ".venv", "tests", "test", "pytest", "node_modules", "docs"}
for path in bundle.rglob("*"):
    if not path.is_file():
        continue
    relative = path.relative_to(bundle)
    if {"win-x86", "win-arm64", "x86"}.intersection(relative.parts) and not (
        relative.as_posix() in (
            "_internal/webview/lib/runtimes/win-x86/native/runtime-directory.txt",
            "_internal/webview/lib/runtimes/win-arm64/native/runtime-directory.txt",
        )
    ):
        raise SystemExit(f"Unexpected native architecture: {relative}")
    if forbidden_parts.intersection(part.lower() for part in relative.parts) or path.name.lower() in (
        "agents.md", "todo.md", "twitchio_tokens.json", "app_settings.json", "personality_settings.json", "custom_commands.json",
    ) or path.name.lower().startswith(".env") or path.suffix.lower() in (
        ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite-wal", ".sqlite-shm",
        ".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".log", ".bak", ".recovery",
    ):
        raise SystemExit(f"Forbidden artifact path: {relative}")
archive = CArchiveReader(str(bundle / "HeetKit.exe"))
pyz_name = next(name for name in archive.toc if name.endswith(".pyz"))
pyz = archive.open_embedded_archive(pyz_name)
for name in pyz.toc:
    if name.split(".")[0] in ("pip", "setuptools") or {"pytest", "unittest", "tests", "test"}.intersection(name.split(".")):
        raise SystemExit(f"Development module bundled: {name}")
if any(name == "pystray" or name.startswith("pystray.") for name in pyz.toc):
    raise SystemExit("pystray must remain replaceable Python source outside PYZ")
for required in (
    "HeetKit.exe", "HeetKit.exe.config", "_internal/app/resources/frontend/index.html", "_internal/app/resources/icon.ico",
    "_internal/app/resources/tray.png", "_internal/pystray/__init__.py", "_internal/certifi/cacert.pem", "_internal/LICENSE", "_internal/PORTABLE.txt",
    "_internal/licenses/Python-LICENSE.txt",
):
    if not (bundle / required).is_file():
        raise SystemExit(f"Required artifact file missing: {required}")
runtime_setting = ET.parse(bundle / "HeetKit.exe.config").find("runtime/loadFromRemoteSources")
if runtime_setting is None or runtime_setting.get("enabled") != "true":
    raise SystemExit("HeetKit.exe.config must enable loading the shipped Internet-zone assemblies")
print(f"Artifact inventory passed: {sum(p.is_file() for p in bundle.rglob('*'))} files, {len(pyz.toc)} frozen modules")
