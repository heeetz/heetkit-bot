"""Exercise the actual publication step with synthetic artifacts and no GitHub calls."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

from app.version import VERSION


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(SHELL is None, reason="Publication uses PowerShell")


def publication(tmp_path, *, notes=None, tag=None):
    version = VERSION
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
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Verify downloads and publish the existing tag", 1)[1]
    script = textwrap.dedent(step.split("run: |\n", 1)[1])
    # The local function captures the actual gh arguments; it never contacts GitHub.
    harness = """$ErrorActionPreference = 'Stop'
$env:PRERELEASE = 'false'
function gh { $args | ConvertTo-Json | Set-Content -LiteralPath 'gh-arguments.json'; $global:LASTEXITCODE = 0 }
""" + f"$env:APP_VERSION = '{version}'\n$env:RELEASE_TAG = '{tag}'\n" + script
    runner = tmp_path / "publish.ps1"
    runner.write_text(harness, encoding="utf-8")
    result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-File", str(runner)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    return result


def test_publication_uses_curated_tagged_notes_and_exact_verified_assets(tmp_path):
    notes = (ROOT / f"docs/releases/v{VERSION}.md").read_text(encoding="utf-8")
    assert notes.startswith(f"# HeetKit v{VERSION}\n")
    result = publication(tmp_path, notes=notes)
    assert result.returncode == 0, result.stderr
    args = json.loads((tmp_path / "gh-arguments.json").read_text(encoding="utf-8-sig"))
    assert args[:6] == ["release", "create", f"v{VERSION}", "--verify-tag", "--notes-file", f"docs/releases/v{VERSION}.md"]
    assert "--generate-notes" not in args
    assert "--prerelease" not in args
    assert len(args[6:]) == 5
    assert {Path(path).name for path in args[6:]} == {path.name for path in (tmp_path / "release-artifacts").iterdir()}


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
