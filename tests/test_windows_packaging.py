"""The Windows staging boundary permits runtime assets, never profile files."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("windows_builder", ROOT / "scripts/build_windows.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_staging_keeps_tray_and_public_defaults_but_ignores_profile_decoys(tmp_path, monkeypatch):
    # Use real declared public resources with synthetic frontend/notice fixtures.
    source = tmp_path / "source"
    stage = tmp_path / "stage"
    import shutil
    shutil.copytree(ROOT / "app/resources", source / "app/resources", ignore=shutil.ignore_patterns("frontend"))
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "packaging/windows/PORTABLE.txt", "third_party_licenses/library/LICENSE"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic notice", encoding="utf-8")
    frontend = source / "frontend/dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    (frontend / "assets/app.js").write_text("// synthetic", encoding="utf-8")
    for relative in ("data/owner.db", ".agent/HANDOFF.md", "app/resources/app_settings.json", "app/resources/filters/private.json"):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private decoy", encoding="utf-8")
    monkeypatch.setattr(builder, "ROOT", source)
    builder.stage_resources(stage)
    assert (stage / "app/resources/tray.png").read_bytes() == (ROOT / "app/resources/tray.png").read_bytes()
    assert (stage / "app/resources/frontend/index.html").is_file()
    assert not any(b"private decoy" in p.read_bytes() for p in stage.rglob("*") if p.is_file())
    (frontend / "owner-settings.json").write_text("private decoy", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unexpected frontend build output"):
        builder.stage_resources(tmp_path / "rejected")


def test_staging_rejects_an_input_outside_source_tree(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    private = tmp_path / "private.json"
    private.write_text("private decoy", encoding="utf-8")
    monkeypatch.setattr(builder, "ROOT", source)
    with pytest.raises((RuntimeError, ValueError)):
        builder.copy(private, source / "stage/private.json")
    assert not (source / "stage/private.json").exists()


def test_build_rejects_native_arm64_before_creating_output(monkeypatch):
    monkeypatch.setattr(builder.sys, "platform", "win32")
    monkeypatch.setattr(builder.sysconfig, "get_platform", lambda: "win-arm64")
    with pytest.raises(SystemExit, match="Windows x64"):
        builder.main()
