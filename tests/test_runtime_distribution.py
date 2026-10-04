"""Focused checks for declared installed resources and source migration boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tomllib

from sqlalchemy.engine import make_url
from app.config.settings import Settings

from app.runtime_paths import (
    DEFAULT_FILTERS,
    DEFAULT_TRIGGERS,
    FILTER_NAMES,
    LEGACY_DATA,
    PACKAGED_FRONTEND,
    SOURCE_ROOT,
    RuntimePaths,
    prepare_runtime_data,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _project_configuration() -> dict[str, object]:
    return tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _materialize_declared_install(install_root: Path) -> None:
    """Create a minimal installed tree from pyproject declarations and package files."""
    project = _project_configuration()
    setuptools = project["tool"]["setuptools"]
    package_find = setuptools["packages"]["find"]
    assert package_find["include"] == ["app*"]

    for init_file in (REPOSITORY_ROOT / "app").rglob("__init__.py"):
        package_directory = init_file.parent
        relative_package = package_directory.relative_to(REPOSITORY_ROOT)
        target_directory = install_root / relative_package
        target_directory.mkdir(parents=True, exist_ok=True)
        for source_file in package_directory.glob("*.py"):
            shutil.copy2(source_file, target_directory / source_file.name)

    for module_name in setuptools["py-modules"]:
        source_file = REPOSITORY_ROOT / f"{module_name}.py"
        assert source_file.is_file()
        shutil.copy2(source_file, install_root / source_file.name)

    package_data = setuptools["package-data"]["app.resources"]
    assert setuptools["include-package-data"] is False
    source_resources = REPOSITORY_ROOT / "app" / "resources"
    target_resources = install_root / "app" / "resources"
    for pattern in package_data:
        if pattern.startswith("frontend/"):
            continue
        for source_file in source_resources.glob(pattern):
            if not source_file.is_file():
                continue
            relative_file = source_file.relative_to(source_resources)
            target_file = target_resources / relative_file
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)

    # A built frontend is an artifact of the installed tree, so keep this fixture synthetic.
    frontend = target_resources / "frontend"
    assets = frontend / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (frontend / "index.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="./assets/app.css">'
        '</head><body><div id="root"></div><script src="./assets/app.js"></script>'
        "</body></html>",
        encoding="utf-8",
    )
    (frontend / "icon.png").write_bytes(b"synthetic frontend icon")
    (assets / "app.css").write_text("#root { color: white; }", encoding="utf-8")
    (assets / "app.js").write_text("document.getElementById('root');", encoding="utf-8")
    for fixture in frontend.rglob("*"):
        if fixture.is_file():
            assert any(fixture.relative_to(target_resources).match(pattern) for pattern in package_data)


def test_runtime_resources_are_declared_and_source_defaults_are_package_local() -> None:
    project = _project_configuration()
    setuptools = project["tool"]["setuptools"]
    package_data = setuptools["package-data"]["app.resources"]

    assert setuptools["py-modules"] == []
    assert not (REPOSITORY_ROOT / "config.py").exists()
    assert "filters/*.txt" in package_data
    assert "frontend/*.html" in package_data
    assert "frontend/*.png" in package_data
    assert "frontend/assets/*" in package_data
    assert DEFAULT_FILTERS == REPOSITORY_ROOT / "app" / "resources" / "filters"
    assert DEFAULT_TRIGGERS == REPOSITORY_ROOT / "app" / "resources" / "default_triggers.json"
    assert PACKAGED_FRONTEND == REPOSITORY_ROOT / "app" / "resources" / "frontend" / "index.html"
    assert SOURCE_ROOT == REPOSITORY_ROOT
    assert LEGACY_DATA == REPOSITORY_ROOT / "data"

    assert DEFAULT_TRIGGERS.is_file()
    assert json.loads(DEFAULT_TRIGGERS.read_text(encoding="utf-8"))["triggers"] == []
    assert all((DEFAULT_FILTERS / filename).is_file() for filename in FILTER_NAMES)


def test_installed_tree_runs_check_and_clean_backend_without_checkout_or_install_writes(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "installed"
    _materialize_declared_install(install_root)
    assert not (install_root / "config.py").exists()
    assert not (install_root / "pyproject.toml").exists()
    assert not (install_root / "frontend").exists()
    assert not (install_root / "tests").exists()
    assert not (install_root / ".agent").exists()
    assert not (install_root / "README.md").exists()
    (install_root / ".env").write_text("TWITCH_BOT_USERNAME=install-decoy\nTWITCH_CLIENT_SECRET=install-secret\n", encoding="utf-8")

    # These decoys model a sibling install/data directory and must remain outside runtime inputs.
    (install_root / "data" / "filters").mkdir(parents=True)
    (install_root / "data" / "app_settings.json").write_text("sibling decoy", encoding="utf-8")
    (install_root / "data" / "filters" / FILTER_NAMES[0]).write_text(
        "sibling decoy", encoding="utf-8"
    )
    cwd = tmp_path / "unrelated-cwd"
    cwd.mkdir()
    (cwd / ".env").write_text(
        "TWITCH_CLIENT_ID=cwd-client\nTWITCH_BOT_USERNAME=cwd-owner\n"
        "TWITCH_CLIENT_SECRET=cwd-secret\n",
        encoding="utf-8",
    )
    profile = tmp_path / "profile"
    before = {path.relative_to(install_root): path.read_bytes() for path in install_root.rglob("*") if path.is_file()}

    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(install_root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TWITCH_BOT_DATA_DIR": str(profile),
        }
    )
    for name in Settings.model_fields:
        environment.pop(name.upper(), None)

    check = subprocess.run(
        [sys.executable, "-m", "app.main", "--check"],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr

    backend_check = """
from pathlib import Path
from types import SimpleNamespace
import os

from app.config.settings import load_settings_with_credentials
from app.app_settings import AppSettingsStore
from app import runtime_paths, webview_host
from app.runtime_paths import DEFAULT_FILTERS, LEGACY_DATA, PACKAGED_FRONTEND, SOURCE_ROOT, RuntimePaths, prepare_runtime_data

# Exercise an installed normal profile, including its usual legacy-migration flag.
profile = Path(os.environ["TWITCH_BOT_DATA_DIR"])
runtime_paths.user_data_path = lambda *args, **kwargs: profile
settings, credentials = load_settings_with_credentials(SimpleNamespace(get=lambda name: None))
assert SOURCE_ROOT is None
assert LEGACY_DATA is None
assert PACKAGED_FRONTEND.is_file()
assert settings.twitch_client_id == ""
assert settings.twitch_bot_username == ""
assert all(not status.configured for status in credentials.statuses())
paths = RuntimePaths.default()
assert paths.is_default_profile
prepare_runtime_data(settings.twitch_token_file, settings.database_url)
backend = webview_host.AsyncioBackendHost(settings)
try:
    backend.start()
    store = AppSettingsStore(paths.app_settings)
    bridge = webview_host.WebUIBridge(backend, app_settings=store, credential_manager=credentials)
    assert bridge.get_twitch_settings()["settings"]["client_id"] == ""
    assert bridge.update_twitch_settings("target", "200", None, "client-id", "bot", "100")["ok"]
    assert bridge.get_twitch_settings()["settings"]["requires_restart"]
    assert bridge.update_ai_provider_settings("gemini-installed", "gemini-installed-fallback")["ok"]
finally:
    backend.close()
saved = AppSettingsStore(paths.app_settings).snapshot()
applied = webview_host.apply_twitch_app_settings(settings, saved)
applied = webview_host.apply_ai_app_settings(applied, saved)
assert applied.twitch_bot_username == "bot"
assert applied.gemini_model == "gemini-installed"
assert "config" not in __import__("sys").modules
assert paths.database.is_file()
assert not paths.tokens.exists()
assert paths.message_triggers.is_file()
for name in ("blocked_words.txt", "blocked_phrases.txt", "blocked_patterns.txt"):
    assert (paths.filters / name).read_bytes() == (DEFAULT_FILTERS / name).read_bytes()
assert DEFAULT_FILTERS.is_dir()
"""
    backend = subprocess.run(
        [sys.executable, "-c", backend_check],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert backend.returncode == 0, backend.stderr
    assert not (cwd / "config").exists()
    assert not (cwd / "data").exists()
    assert profile.exists()
    after = {path.relative_to(install_root): path.read_bytes() for path in install_root.rglob("*") if path.is_file()}
    assert after == before


def test_relative_legacy_candidates_ignore_unrelated_working_directory(
    tmp_path: Path, monkeypatch
) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "filters").mkdir()
    (legacy / "twitchio_tokens.json").write_text("legacy-token", encoding="utf-8")
    with sqlite3.connect(legacy / "twitch_bot.db") as connection:
        connection.execute("CREATE TABLE source (value TEXT)")
        connection.execute("INSERT INTO source VALUES ('legacy')")
        connection.commit()

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "twitchio_tokens.json").write_text("unrelated-token", encoding="utf-8")
    with sqlite3.connect(unrelated / "twitch_bot.db") as connection:
        connection.execute("CREATE TABLE source (value TEXT)")
        connection.execute("INSERT INTO source VALUES ('unrelated')")
        connection.commit()
    monkeypatch.chdir(unrelated)

    paths = RuntimePaths(tmp_path / "profile")
    token_file, database_url = prepare_runtime_data(
        "twitchio_tokens.json",
        "sqlite+aiosqlite:///twitch_bot.db",
        paths=paths,
        legacy_data=legacy,
        migrate_legacy=True,
    )

    assert Path(token_file).read_text(encoding="utf-8") == "legacy-token"
    assert make_url(database_url).database == str(paths.database)
    with sqlite3.connect(paths.database) as connection:
        assert connection.execute("SELECT value FROM source").fetchone() == ("legacy",)
