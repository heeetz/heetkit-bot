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
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "packaging/windows/PORTABLE.txt",
                 "packaging/windows/redistribution.json", "third_party_licenses/library/LICENSE"):
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
    assert (stage / "licenses/windows-redistribution.json").read_text() == "synthetic notice"
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


redistribution_spec = importlib.util.spec_from_file_location(
    "windows_redistribution", ROOT / "scripts/windows_redistribution.py"
)
redistribution = importlib.util.module_from_spec(redistribution_spec)
redistribution_spec.loader.exec_module(redistribution)


@pytest.fixture
def reviewed_artifact(tmp_path):
    import hashlib
    import json

    bundle = tmp_path / "HeetKit"
    binary = bundle / "_internal/example.dll"
    notice = bundle / "_internal/third_party_licenses/native/example/LICENSE"
    for path, data in ((binary, b"MZreviewed version 1"), (notice, b"exact upstream license")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    policy = tmp_path / "redistribution.json"
    policy.write_text(json.dumps({
        "schema": "heetkit.windows-redistribution.v1", "python_version": "3.14.7",
        "native_files": {"_internal/example.dll": {
            "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "version": "1",
        }},
        "required_notices": {notice.relative_to(bundle).as_posix(): {
            "sha256": hashlib.sha256(notice.read_bytes()).hexdigest(),
        }},
        "required_documents": [], "unresolved_findings": ["Owner review required"],
    }), encoding="utf-8")
    staged = bundle / redistribution.STAGED_POLICY
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(policy.read_bytes())
    return bundle, policy, binary, notice


def test_reviewed_artifact_reports_evidence_without_claiming_clearance(reviewed_artifact):
    bundle, policy, _, _ = reviewed_artifact
    result = redistribution.validate(bundle, policy)
    assert result == {"native_files": 1, "required_notices": 1,
                      "unresolved_findings": ["Owner review required"]}


@pytest.mark.parametrize("change, message", [
    ("missing-notice", "notice missing"), ("altered-notice", "notice hash mismatch"),
    ("changed-version", "Native hash/version mismatch"), ("missing-binary", "Missing reviewed native"),
    ("new-dll", "Unexpected native"), ("renamed-pe", "Unexpected native"),
    ("policy", "mismatched staged"), ("python-version", "Python version differs"),
])
def test_artifact_rejects_notice_and_native_drift(reviewed_artifact, change, message):
    bundle, policy, binary, notice = reviewed_artifact
    if change == "missing-notice":
        notice.unlink()
    elif change == "altered-notice":
        notice.write_bytes(b"truncated")
    elif change == "changed-version":
        binary.write_bytes(b"MZdifferent version 2")
    elif change == "missing-binary":
        binary.unlink()
    elif change in ("new-dll", "renamed-pe"):
        (bundle / ("new.dll" if change == "new-dll" else "hidden.dat")).write_bytes(b"MZnew component")
    elif change == "policy":
        (bundle / redistribution.STAGED_POLICY).write_text("{}", encoding="utf-8")
    elif change == "python-version":
        (bundle / "BUILD-MANIFEST.json").write_text('{"python": "3.15.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        redistribution.validate(bundle, policy)


@pytest.mark.parametrize("tamper", [None, "archive", "member"])
def test_runtime_staging_requires_the_reviewed_archive_and_binary(tmp_path, monkeypatch, tamper):
    import hashlib
    import io
    import json
    import zipfile

    binary = b"MZreviewed SDK DLL"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("redist/x64/runtime.dll", binary)
    data = stream.getvalue()
    source = tmp_path / "source"
    policy = source / "packaging/windows/redistribution.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(json.dumps({
        "distributions": {"sdk": {
            "url": "https://example.invalid/official-sdk.nupkg",
            "sha256": "0" * 64 if tamper == "archive" else hashlib.sha256(data).hexdigest(),
        }},
        "pinned_runtime": {"distribution": "sdk", "files": {"runtime.dll": {
            "member": "redist/x64/runtime.dll",
            "sha256": "0" * 64 if tamper == "member" else hashlib.sha256(binary).hexdigest(),
        }}},
    }), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    stage = tmp_path / "stage"
    monkeypatch.setattr(builder, "ROOT", source)
    monkeypatch.setattr(builder.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(data))
    if tamper:
        with pytest.raises(ValueError, match="hash mismatch"):
            builder.stage_native_runtime(stage, work)
        assert not (stage / "native-runtime/runtime.dll").exists()
    else:
        builder.stage_native_runtime(stage, work)
        assert (stage / "native-runtime/runtime.dll").read_bytes() == binary
