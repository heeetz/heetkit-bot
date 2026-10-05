"""Installer input checks reject corrupted, mismatched or unsafe portable archives."""

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer_builder", ROOT / "scripts/build_installer.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def portable(tmp_path, *, version="0.1.3", change=None, extra=None, link=False):
    files = {"HeetKit.exe": b"synthetic executable", "HeetKit.exe.config": b"synthetic config"}
    manifest = {"version": version, "files": [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()
    ]}
    if change:
        files["HeetKit.exe"] = b"tampered executable"
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, data in files.items():
            output.writestr(f"HeetKit/{name}", data)
        output.writestr("HeetKit/BUILD-MANIFEST.json", json.dumps(manifest))
        if extra:
            entry = zipfile.ZipInfo(extra)
            if link:
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(entry, "private decoy")
    archive.with_suffix(".zip.sha256").write_text(
        f"{builder.sha256(archive)}  {archive.name}\n", encoding="ascii"
    )
    return archive


def test_exact_manifest_payload_roundtrip(tmp_path):
    archive = portable(tmp_path)
    stage = tmp_path / "stage"
    result = builder.stage_portable(archive, stage, "0.1.3")
    assert result["version"] == "0.1.3"
    assert (stage / "HeetKit.exe").read_bytes() == b"synthetic executable"
    assert {p.name for p in stage.iterdir()} == {"HeetKit.exe", "HeetKit.exe.config", "BUILD-MANIFEST.json"}


def test_checksum_mismatch_stops_before_extraction(tmp_path):
    archive = portable(tmp_path)
    with archive.open("ab") as output:
        output.write(b"changed zip")
    with pytest.raises(ValueError, match="ZIP checksum mismatch"):
        builder.stage_portable(archive, tmp_path / "stage", "0.1.3")
    assert not (tmp_path / "stage").exists()


def test_version_mismatch_stops_before_extraction(tmp_path):
    archive = portable(tmp_path, version="0.1.2")
    with pytest.raises(ValueError, match="canonical application version"):
        builder.stage_portable(archive, tmp_path / "stage", "0.1.3")
    assert not (tmp_path / "stage").exists()


def test_payload_hash_mismatch_is_rejected(tmp_path):
    archive = portable(tmp_path, change=True)
    with pytest.raises(ValueError, match="payload hash mismatch"):
        builder.stage_portable(archive, tmp_path / "stage", "0.1.3")


def test_unmanifested_private_file_is_rejected(tmp_path):
    archive = portable(tmp_path, extra="HeetKit/auth/twitchio_tokens.json")
    with pytest.raises(ValueError, match="inventory differs"):
        builder.stage_portable(archive, tmp_path / "stage", "0.1.3")
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("entry", [
    "HeetKit/../../escaped.txt", "HeetKit/../escaped.txt", "HeetKit\\escaped.txt",
    "HeetKit/file:stream", "/HeetKit/escaped.txt", "OtherRoot/file.txt",
    "HeetKit/file. ", "HeetKit/HEETKIT.EXE",
])
def test_unsafe_and_duplicate_zip_entries_are_rejected(tmp_path, entry):
    archive = portable(tmp_path, extra=entry)
    with pytest.raises(ValueError):
        builder.stage_portable(archive, tmp_path / "stage", "0.1.3")
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "stage").exists()


def test_symbolic_link_is_rejected(tmp_path):
    archive = portable(tmp_path, extra="HeetKit/linked.txt", link=True)
    with pytest.raises(ValueError, match="Unexpected ZIP entry"):
        builder.stage_portable(archive, tmp_path / "stage", "0.1.3")
    assert not (tmp_path / "stage").exists()
