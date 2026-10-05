"""Wrap a verified Phase A ZIP in a pinned Inno Setup installer; never read profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
INNO_VERSION = "6.7.3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name or "\\" in name or ":" in name or path.is_absolute()
        or any(part in ("", ".", "..") for part in name.split("/"))
        or any(part.endswith((".", " ")) for part in path.parts)
    ):
        raise ValueError(f"Unsafe payload path: {name}")
    return path


def stage_portable(archive_path: Path, stage: Path, version: str) -> dict:
    """Require an exact, hash-verified manifest and reject ZIP extraction hazards."""
    checksum_path = archive_path.with_suffix(".zip.sha256")
    expected = checksum_path.read_text(encoding="ascii").strip()
    if expected != f"{sha256(archive_path)}  {archive_path.name}":
        raise ValueError("Portable ZIP checksum mismatch")
    with zipfile.ZipFile(archive_path) as archive:
        files = {}
        seen = set()
        for item in archive.infolist():
            path = payload_path(item.filename.rstrip("/") if item.is_dir() else item.filename)
            if path.parts[0] != "HeetKit" or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError(f"Unexpected ZIP entry: {item.filename}")
            key = path.as_posix().casefold()
            if key in seen:
                raise ValueError(f"Duplicate ZIP entry: {item.filename}")
            seen.add(key)
            if not item.is_dir():
                files[path.relative_to("HeetKit").as_posix()] = item
        manifest = json.loads(archive.read(files["BUILD-MANIFEST.json"]))
        if manifest["version"] != version:
            raise ValueError("Portable manifest and canonical application version disagree")
        declared = {}
        for item in manifest["files"]:
            name = payload_path(item["path"]).as_posix()
            if name.casefold() in declared or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise ValueError(f"Invalid manifest entry: {name}")
            declared[name.casefold()] = item
        if set(files) - {"BUILD-MANIFEST.json"} != {item["path"] for item in declared.values()}:
            raise ValueError("Portable file inventory differs from its manifest")
        for name, item in files.items():
            data = archive.read(item)
            if name != "BUILD-MANIFEST.json" and hashlib.sha256(data).hexdigest() != declared[name.casefold()]["sha256"]:
                raise ValueError(f"Portable payload hash mismatch: {name}")
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    return manifest


def build(archive: Path, compiler: Path, version: str) -> None:
    output = ROOT / "dist" / f"HeetKit-{version}-windows-x64-setup.exe"
    if output.exists():
        raise ValueError(f"Installer already exists; move it aside before rebuilding: {output}")
    work = ROOT / "build/installer" / uuid.uuid4().hex
    bundle = work / "HeetKit"
    stage_portable(archive, bundle, version)
    # Reuse the Phase A inspection, including the actual executable's frozen modules.
    subprocess.run([sys.executable, str(ROOT / "scripts/inspect_windows_bundle.py"), str(bundle)], check=True)
    license_path = ROOT / "third_party_licenses/inno-setup/LICENSE.txt"
    notices = [
        "HeetKit license and notices\n\nCreated by heeetz. Not affiliated with or endorsed by Twitch.\n",
        *(bundle.joinpath("_internal", name).read_text(encoding="utf-8") for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")),
        license_path.read_text(encoding="utf-8"),
    ]
    notice_page = work / "LICENSE-NOTICES.txt"
    notice_page.write_text("\n\n".join(notices), encoding="utf-8-sig")
    subprocess.run([
        str(compiler), "/Qp", f"/DAppVersion={version}", f"/DBundleDir={bundle}",
        f"/DNoticePage={notice_page}", f"/DOutputDir={output.parent}",
        str(ROOT / "packaging/windows/HeetKit.iss"),
    ], check=True)
    checksum = sha256(output)
    output.with_suffix(".exe.sha256").write_text(f"{checksum}  {output.name}\n", encoding="ascii")
    output.with_suffix(".exe.build.json").write_text(json.dumps({
        "version": version, "inno_setup": INNO_VERSION,
        "portable_zip": archive.name, "portable_sha256": sha256(archive),
        "payload_manifest_sha256": sha256(bundle / "BUILD-MANIFEST.json"),
        "installer_sha256": checksum,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Version: {version}\nInstaller: {output}\nSHA-256: {checksum}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inno-compiler", type=Path, required=True)
    parser.add_argument("--portable-zip", type=Path)
    arguments = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Installer build requires Windows.")
    sys.path.insert(0, str(ROOT))
    from app.version import VERSION

    archive = arguments.portable_zip or ROOT / "dist" / f"HeetKit-{VERSION}-windows-x64.zip"
    build(archive.resolve(), arguments.inno_compiler.resolve(), VERSION)


if __name__ == "__main__":
    main()
