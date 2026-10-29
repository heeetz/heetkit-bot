"""Exercise the Windows source launcher with synthetic build and application tools."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows batch launcher")


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    shutil.copy2(Path(__file__).parents[1] / "run.bat", root / "run.bat")
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(sys.executable, scripts / "python.exe")
    (root / ".venv" / "pyvenv.cfg").write_text(
        f"home = {sys.base_prefix}\ninclude-system-site-packages = false\n",
        encoding="utf-8",
    )
    app = root / "app"
    app.mkdir()
    (app / "__init__.py").touch()
    (app / "main.py").write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path('launch.json').write_text(json.dumps(sys.argv[1:]))\n"
        "sys.exit(int(os.environ.get('TEST_APP_EXIT', '0')))\n",
        encoding="utf-8",
    )
    tools = root / "tools"
    tools.mkdir()
    (tools / "npm.cmd").write_text(
        "@echo off\necho %* > build.txt\nexit /b %TEST_BUILD_EXIT%\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PATH": f"{tools};{sys.base_prefix};{os.environ['SystemRoot']}\\System32",
           "TEST_BUILD_EXIT": "0"}
    return root, env


def run_launcher(root, env):
    return subprocess.run(
        [os.environ["COMSPEC"], "/d", "/c", "call", str(root / "run.bat"),
         "--stopped", "--data-dir", "synthetic profile"],
        cwd=root.parent, env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=20, check=False,
    )


def test_launcher_rebuilds_on_every_launch_and_forwards_arguments(launcher):
    root, env = launcher
    for _ in range(2):
        result = run_launcher(root, env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (root / "build.txt").read_text().strip() == f'--prefix "{root}\\frontend" run build'
        assert json.loads((root / "launch.json").read_text()) == [
            "--stopped", "--data-dir", "synthetic profile",
        ]
        (root / "build.txt").unlink()


def test_launcher_stops_when_build_fails(launcher):
    root, env = launcher
    result = run_launcher(root, {**env, "TEST_BUILD_EXIT": "7"})
    assert result.returncode == 1
    assert "Frontend build failed" in result.stdout
    assert not (root / "launch.json").exists()


def test_launcher_reports_missing_npm(launcher):
    root, env = launcher
    (root / "tools" / "npm.cmd").unlink()
    result = run_launcher(root, env)
    assert result.returncode == 1
    assert "npm was not found" in result.stdout
    assert not (root / "launch.json").exists()


def test_launcher_preserves_application_exit_code(launcher):
    root, env = launcher
    result = run_launcher(root, {**env, "TEST_APP_EXIT": "9"})
    assert result.returncode == 9
    assert "HeetKit stopped with exit code 9" in result.stdout
    assert "Press any key" in result.stdout


def test_launcher_does_not_pause_after_a_successful_exit(launcher):
    root, env = launcher
    result = run_launcher(root, env)
    assert result.returncode == 0
    assert "Press any key" not in result.stdout
