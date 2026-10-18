"""Secret-file boundaries and local health diagnostics, without network or live data."""

import json
import os
from pathlib import Path
import tomllib

import pytest

from app.headless import HeadlessError, secret_file_settings
from app.headless_health import HealthFile, healthy


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch):
    for name in ("TWITCH_CLIENT_SECRET", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name + "_FILE", raising=False)


def test_secret_files_are_private_inputs_without_environment_publication(tmp_path, monkeypatch):
    path = tmp_path / "secret"
    path.write_text("synthetic-value\n", encoding="utf-8")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET_FILE", str(path))
    assert secret_file_settings() == {"twitch_client_secret": "synthetic-value"}
    assert "TWITCH_CLIENT_SECRET" not in os.environ
    path.write_text("\n", encoding="utf-8")
    assert secret_file_settings() == {}  # Optional Gemini may use an empty file.


@pytest.mark.parametrize("content", [b"x" * 16385, b"private\x00value", b"private\nvalue", b"\xffprivate"])
def test_invalid_secret_file_fails_without_disclosing_contents(tmp_path, monkeypatch, content):
    path = tmp_path / "private-path-sentinel"
    path.write_bytes(content)
    monkeypatch.setenv("TWITCH_CLIENT_SECRET_FILE", str(path))
    with pytest.raises(HeadlessError) as error:
        secret_file_settings()
    assert "TWITCH_CLIENT_SECRET_FILE" in str(error.value)
    assert "private" not in str(error.value)


def test_missing_directory_and_conflicting_secret_sources_fail_safely(tmp_path, monkeypatch):
    for path in (tmp_path / "missing", tmp_path):
        monkeypatch.setenv("GEMINI_API_KEY_FILE", str(path))
        with pytest.raises(HeadlessError, match="Cannot read GEMINI_API_KEY_FILE"):
            secret_file_settings()
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic")
    with pytest.raises(HeadlessError, match="Set only GEMINI_API_KEY or GEMINI_API_KEY_FILE"):
        secret_file_settings()


def test_fifo_secret_is_rejected_without_blocking(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX FIFO")
    path = tmp_path / "fifo"
    os.mkfifo(path)
    monkeypatch.setenv("TWITCH_CLIENT_SECRET_FILE", str(path))
    with pytest.raises(HeadlessError, match="regular"):
        secret_file_settings()


def test_health_requires_fresh_connected_heartbeat_and_clears_on_stop(tmp_path, monkeypatch):
    path = tmp_path / "health.json"
    heartbeat = HealthFile(path)
    assert not healthy(path)
    heartbeat.update("starting")
    assert not healthy(path)
    heartbeat.update("connected")
    assert healthy(path)
    original = path.read_bytes()
    heartbeat.update("connected")
    assert path.read_bytes() == original
    time_before = json.loads(original)["updated"]
    monkeypatch.setattr("app.headless_health.time.monotonic", lambda: time_before + 16)
    assert not healthy(path)
    heartbeat.update("reconnecting")
    assert not healthy(path)
    heartbeat.clear()
    assert not path.exists()


@pytest.mark.parametrize("content", ["null", "[]", "{", "x" * 1025,
    json.dumps({"pid": True, "state": "connected", "updated": 1}),
    json.dumps({"pid": 1, "state": "connected", "updated": float("nan")})])
def test_health_rejects_malformed_data_without_tracebacks(tmp_path, content):
    path = tmp_path / "health.json"
    path.write_text(content)
    assert not healthy(path)


def test_backend_dependencies_exclude_desktop_and_linux_lock_preserves_shared_pins():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not any(item.startswith(("keyring", "pywebview", "pystray")) for item in project["dependencies"])
    assert {item.split(">=")[0] for item in project["optional-dependencies"]["desktop"]} == {"keyring", "pywebview", "pystray"}
    windows = dict(line.split("==") for line in (root / "packaging/windows/requirements.txt").read_text().splitlines() if "==" in line)
    for line in (root / "packaging/linux/requirements.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        requirement, digest = line.split(" --hash=sha256:")
        name, version = requirement.split("==")
        assert len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)
        assert name.lower().replace("_", "-") not in {"keyring", "pywebview", "pystray", "pyinstaller", "pillow", "bottle"}
        if name.lower() == "multidict":
            # Linux must not inherit the older Windows redistribution baseline's
            # GHSA-54p9-h82j-f925 affected version (6.7.0 through 6.9.0).
            assert tuple(map(int, version.split("."))) >= (6, 9, 1)
        else:
            assert windows[name.lower().replace("_", "-")] == version
