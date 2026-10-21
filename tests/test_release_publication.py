"""Exercise the actual publication step with synthetic artifacts and no GitHub calls."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest

from app.version import VERSION


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(SHELL is None, reason="Publication uses PowerShell")


def workflow_script(name):
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    step = workflow.split(f"- name: {name}", 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(step.split("run: |\n", 1)[1])


def version_metadata(tmp_path, *, version=VERSION, tag=None, event="push"):
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    source = (ROOT / "app/version.py").read_text(encoding="utf-8")
    (package / "version.py").write_text(source.replace(f'VERSION = "{VERSION}"', f'VERSION = "{version}"'), encoding="utf-8")
    interpreter = sys.executable.replace("'", "''")
    harness = f"""$ErrorActionPreference = 'Stop'
function python {{ & '{interpreter}' @args }}
$env:GITHUB_EVENT_NAME = '{event}'
$env:GITHUB_REF_TYPE = 'tag'
$env:GITHUB_REF_NAME = '{tag or 'v' + version}'
$env:GITHUB_OUTPUT = 'version-output'
""" + workflow_script("Read canonical application version and validate release tag")
    runner = tmp_path / "version.ps1"
    runner.write_text(harness, encoding="utf-8")
    return subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-File", str(runner)],
                          cwd=tmp_path, capture_output=True, text=True, timeout=30)


def publication(tmp_path, *, notes=None, tag=None, version=VERSION, prerelease="false", change=None):
    if tag is None:
        tag = f"v{version}"
    base = f"HeetKit-{version}-windows-x64"
    artifacts = tmp_path / "release-artifacts"
    artifacts.mkdir()
    hashes = {}
    for suffix in (".zip", "-setup.exe"):
        name = base + suffix
        payload = ("synthetic " + name).encode()
        (artifacts / name).write_bytes(payload)
        hashes[suffix] = hashlib.sha256(payload).hexdigest()
        (artifacts / (name + ".sha256")).write_text(f"{hashes[suffix]}  {name}\n", encoding="ascii")
    (artifacts / (base + "-setup.exe.build.json")).write_text(json.dumps({
        "version": version, "portable_zip": base + ".zip", "portable_sha256": hashes[".zip"],
        "installer_sha256": hashes["-setup.exe"],
    }), encoding="utf-8")
    if notes is not None:
        path = tmp_path / f"docs/releases/v{version}.md"
        path.parent.mkdir(parents=True)
        path.write_text(notes, encoding="utf-8")
    if change == "zip":
        (artifacts / (base + ".zip")).write_bytes(b"tampered")
    elif change == "installer":
        (artifacts / (base + "-setup.exe")).write_bytes(b"tampered")
    elif change == "trace":
        (artifacts / (base + "-setup.exe.build.json")).write_text(json.dumps({
            "version": version, "portable_zip": base + ".zip", "portable_sha256": "0" * 64,
            "installer_sha256": hashes["-setup.exe"],
        }), encoding="utf-8")
    elif change == "extra":
        (artifacts / "private-profile.json").write_text("synthetic decoy", encoding="utf-8")
    script = workflow_script("Verify downloads and publish the existing tag")
    # The local function captures the actual gh arguments; it never contacts GitHub.
    harness = """$ErrorActionPreference = 'Stop'
function gh { $args | ConvertTo-Json | Set-Content -LiteralPath 'gh-arguments.json'; $global:LASTEXITCODE = 0 }
""" + f"$env:APP_VERSION = '{version}'\n$env:RELEASE_TAG = '{tag}'\n$env:PRERELEASE = '{prerelease}'\n" + script
    runner = tmp_path / "publish.ps1"
    runner.write_text(harness, encoding="utf-8")
    result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-File", str(runner)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    return result


@pytest.mark.parametrize("version,prerelease", [("1.3.0", "false"), ("1.4.0-beta.1", "true"), ("0.1.3", "true")])
def test_publication_uses_curated_tagged_notes_and_exact_verified_assets(tmp_path, version, prerelease):
    metadata_result = version_metadata(tmp_path, version=version)
    assert metadata_result.returncode == 0, metadata_result.stderr
    metadata = dict(line.split("=", 1) for line in (tmp_path / "version-output").read_text(encoding="utf-8-sig").splitlines())
    assert metadata == {"version": version, "prerelease": prerelease}
    notes = (ROOT / f"docs/releases/v{version}.md").read_text(encoding="utf-8") if version != "0.1.3" else "# HeetKit v0.1.3\n" + "Test release. " * 20
    assert notes.startswith(f"# HeetKit v{version}\n")
    result = publication(tmp_path, notes=notes, **metadata)
    assert result.returncode == 0, result.stderr
    args = json.loads((tmp_path / "gh-arguments.json").read_text(encoding="utf-8-sig"))
    assert args[:6] == ["release", "create", f"v{version}", "--verify-tag", "--notes-file", f"docs/releases/v{version}.md"]
    assert "--generate-notes" not in args
    offset = 6
    if prerelease == "true":
        assert args[6:8] == ["--prerelease", "--latest=false"]
        offset = 8
    else:
        assert "--prerelease" not in args
        assert "--latest=false" not in args
    assert len(args[offset:]) == 5
    assert {Path(path).name for path in args[offset:]} == {path.name for path in (tmp_path / "release-artifacts").iterdir()}


@pytest.mark.parametrize("version,tag,event,reason", [
    (VERSION, f"v{VERSION}-mismatch", "push", "must match canonical version"),
    ("1.4.0-beta.01", None, "push", "Cannot validate"),
    ("01.4.0", None, "push", "Cannot validate"),
    ("1.4.0+build", None, "push", "Cannot validate"),
    ("1.4.0-beta", None, "workflow_dispatch", "Cannot validate"),
])
def test_invalid_version_or_mismatched_tag_blocks_build(tmp_path, version, tag, event, reason):
    result = version_metadata(tmp_path, version=version, tag=tag, event=event)
    assert result.returncode != 0
    assert reason in result.stderr
    assert not (tmp_path / "version-output").exists()


@pytest.mark.parametrize("change,reason", [
    ("zip", "Release checksum mismatch"), ("installer", "Release checksum mismatch"),
    ("trace", "Installer traceability"), ("extra", "Unexpected files"),
])
def test_invalid_artifacts_prevent_prerelease_publication(tmp_path, change, reason):
    notes = (ROOT / f"docs/releases/v{VERSION}.md").read_text(encoding="utf-8")
    result = publication(tmp_path, notes=notes, prerelease="true", change=change)
    assert result.returncode != 0
    assert reason in result.stderr
    assert not (tmp_path / "gh-arguments.json").exists()


@pytest.mark.parametrize("notes,tag,reason", [
    (None, None, "Missing curated release notes"),
    ("# Wrong release\n" + "Old notes " * 20, None, "matching release version"),
    (f"# HeetKit v{VERSION}\n", None, "matching release version"),
    (None, f"v{VERSION}-mismatch", "Release tag/version mismatch"),
])
def test_invalid_release_notes_or_tag_prevent_publication(tmp_path, notes, tag, reason):
    result = publication(tmp_path, notes=notes, tag=tag)
    assert result.returncode != 0
    assert reason in result.stderr
    assert not (tmp_path / "gh-arguments.json").exists()
