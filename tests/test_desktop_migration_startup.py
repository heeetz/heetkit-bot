"""Desktop startup recovery uses disposable profiles, without accounts or GUI launch."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config.settings import Settings
from app.database import migrations
from app.runtime_paths import RuntimePaths
from app.webview_host import AsyncioBackendHost, WebUIBridge, expose_frontend_operations


@pytest.fixture
def legacy_settings(tmp_path, monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path / "synthetic-profile"))
    paths = RuntimePaths.default()
    paths.database.parent.mkdir(parents=True)
    stamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(" ")
    with closing(sqlite3.connect(paths.database)) as connection:
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, twitch_user_id VARCHAR(32), username VARCHAR(64), created_at DATETIME, last_seen_at DATETIME);
            CREATE TABLE ai_memory_entries (id INTEGER PRIMARY KEY, twitch_user_id VARCHAR(32), request_text VARCHAR(500), response_text VARCHAR(500), created_at DATETIME);
        """)
        connection.execute("INSERT INTO users VALUES (1,'123','syntheticviewer',?,?)", (stamp, stamp))
        connection.execute("INSERT INTO ai_memory_entries VALUES (1,'123','synthetic question','synthetic answer',?)", (stamp,))
        connection.commit()
    return Settings(database_url="sqlite+aiosqlite:///" + str(paths.database), twitch_channel="configured_channel",
                    twitch_channel_user_id="200"), paths


def test_missing_mapping_opens_guarded_startup_and_confirmation_resumes_once(legacy_settings, monkeypatch):
    from webview.window import Window
    settings, paths = legacy_settings
    connect = AsyncMock(return_value=True)
    monkeypatch.setattr("app.webview_host.BotRuntime.start_bot", connect)
    backend = AsyncioBackendHost(settings, auto_start=True)
    mapping = paths.database.parent / "legacy-channel-mapping.json"
    try:
        backend.start(timeout=3)
        assert backend.startup_status()["state"] == "mapping_required"
        assert backend.startup_status()["suggested_channel_id"] == "200"
        assert backend.application.database._retention_task is None
        connect.assert_not_awaited()
        assert not mapping.exists()
        bridge = WebUIBridge(backend)
        window = Window("synthetic-startup", "Startup", "http://127.0.0.1:54321/index.html")
        window.real_url = window.original_url
        monkeypatch.setattr(window, "get_current_url", lambda: window.real_url)
        expose_frontend_operations(window, bridge)
        window.events.initialized.set("edgechromium")
        assert window._functions["get_app_status"]()["ok"] is False
        assert window._functions["start_bot"]()["ok"] is False
        for channel_id, confirmed in (("300", False), ("nickname", True), ("", True), ("300", 1)):
            assert not bridge.confirm_legacy_channel(channel_id, confirmed)["ok"]
            assert not mapping.exists()
        assert bridge.confirm_legacy_channel("300", True) == {"ok": True}
        assert json.loads(mapping.read_text()) == {"version": 1, "channel_id": "300"}
        assert backend.startup_status()["state"] == "ready"
        assert backend.application.database._retention_task is not None
        connect.assert_awaited_once()
        assert not bridge.confirm_legacy_channel("400", True)["ok"]
        assert json.loads(mapping.read_text())["channel_id"] == "300"
        assert window._functions["get_app_status"]()["channel"] == "configured_channel"
        async def presence():
            return await backend.application.services.users.get_by_twitch_user_id("123", channel_id="300")
        assert backend.submit(presence()).result(timeout=3).username == "syntheticviewer"
    finally:
        backend.close()
    backup = migrations._recovery_paths(paths.database)[1]
    before = backup.stat().st_mtime_ns
    restarted = AsyncioBackendHost(settings)
    try:
        restarted.start(timeout=3)
        assert restarted.startup_status()["state"] == "ready"
        assert backup.stat().st_mtime_ns == before
    finally:
        restarted.close()


def test_cancel_leaves_mapping_unsaved_and_legacy_rows_intact(legacy_settings):
    settings, paths = legacy_settings
    backend = AsyncioBackendHost(settings)
    destroyed = []
    try:
        backend.start(timeout=3)
        bridge = WebUIBridge(backend)
        bridge._window = SimpleNamespace(destroy=lambda: destroyed.append(True))
        assert bridge.cancel_desktop_startup() == {"ok": True}
        assert destroyed == [True]
    finally:
        backend.close()
    assert not (paths.database.parent / "legacy-channel-mapping.json").exists()
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM ai_memory_entries").fetchone() == (1,)


def test_malformed_existing_mapping_is_actionable_and_never_prompted_or_overwritten(legacy_settings):
    settings, paths = legacy_settings
    mapping = paths.database.parent / "legacy-channel-mapping.json"
    mapping.write_text("PRIVATE invalid json")
    backend = AsyncioBackendHost(settings)
    try:
        with pytest.raises(migrations.DatabaseMigrationError) as error:
            backend.start(timeout=3)
        assert not isinstance(error.value, migrations.LegacyChannelMappingRequired)
        assert "permissions" in error.value.operator_message
        assert "PRIVATE" not in error.value.operator_message
        assert mapping.read_text() == "PRIVATE invalid json"
    finally:
        backend.close()


def test_resume_surfaces_actionable_backup_error_without_starting_workers(legacy_settings, monkeypatch):
    settings, paths = legacy_settings
    def fail(*_):
        raise migrations.DatabaseMigrationError("Recovery backup verification failed.")
    monkeypatch.setattr(migrations, "_backup", fail)
    backend = AsyncioBackendHost(settings)
    try:
        backend.start(timeout=3)
        result = WebUIBridge(backend).confirm_legacy_channel("300", True)
        assert result["ok"] is False
        assert "Recovery backup verification failed" in result["error"]
        assert "Keep the database and recovery copies" in result["error"]
        assert backend.startup_status()["state"] == "failed"
        assert backend.application.database._retention_task is None
        assert json.loads((paths.database.parent / "legacy-channel-mapping.json").read_text())["channel_id"] == "300"
    finally:
        backend.close()


def test_mapping_save_failure_is_sanitized_and_existing_choice_is_never_replaced(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.db"
    migrations.save_legacy_channel_mapping(path, "300")
    with pytest.raises(migrations.DatabaseMigrationError, match="already exists"):
        migrations.save_legacy_channel_mapping(path, "400")
    assert json.loads((tmp_path / "legacy-channel-mapping.json").read_text())["channel_id"] == "300"
    def fail(*_):
        raise OSError("PRIVATE host path")
    monkeypatch.setattr(migrations, "_private_json", fail)
    with pytest.raises(migrations.DatabaseMigrationError, match="permissions") as error:
        migrations.save_legacy_channel_mapping(path, "400")
    assert "PRIVATE" not in error.value.operator_message
    assert list(tmp_path.glob(".legacy-channel-mapping-*.tmp")) == []


def test_desktop_entrypoint_shows_actionable_migration_errors(legacy_settings, monkeypatch, capsys):
    import sys
    from app.webview_host import main
    settings, _ = legacy_settings
    notices = []
    monkeypatch.setattr(sys, "argv", ["heetkit", "--stopped"])
    monkeypatch.setattr("app.webview_host.ensure_windows_runtime", lambda: None)
    monkeypatch.setattr("app.webview_host.load_settings_with_credentials", lambda: (settings, None))
    monkeypatch.setattr("app.webview_host.prepare_runtime_data", lambda token, database: (token, database))
    monkeypatch.setattr("app.webview_host.configure_logging", lambda _: None)
    monkeypatch.setattr("app.webview_host.resolve_frontend_url", lambda _: "synthetic-frontend")
    def fail(*_, **__):
        raise migrations.DatabaseMigrationError("Unsupported database version; use a compatible application.")
    monkeypatch.setattr("app.webview_host.run_desktop_host", fail)
    monkeypatch.setattr("app.webview_host.notify_existing_desktop", notices.append)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    output = capsys.readouterr().err
    assert "use a compatible application" in output
    assert "Keep the database and recovery copies" in output
    assert "Traceback" not in output
    assert len(notices) == 1 and "Unsupported database version" in notices[0]


def test_close_during_confirmation_waits_for_the_private_writer(legacy_settings, monkeypatch):
    import threading
    settings, paths = legacy_settings
    entered, release = threading.Event(), threading.Event()
    original = migrations.save_legacy_channel_mapping
    def pause(*args):
        entered.set()
        assert release.wait(5)
        original(*args)
    monkeypatch.setattr("app.database.database.save_legacy_channel_mapping", pause)
    backend = AsyncioBackendHost(settings)
    backend.start(timeout=3)
    result = []
    confirmation = threading.Thread(target=lambda: result.append(WebUIBridge(backend).confirm_legacy_channel("300", True)))
    closer = threading.Thread(target=backend.close)
    try:
        confirmation.start()
        assert entered.wait(3)
        closer.start()
        closer.join(timeout=0.05)
        assert closer.is_alive()
        release.set()
        confirmation.join(timeout=3)
        closer.join(timeout=3)
        assert not confirmation.is_alive() and not closer.is_alive()
        assert result[0]["ok"] is False
        assert json.loads((paths.database.parent / "legacy-channel-mapping.json").read_text())["channel_id"] == "300"
        with closing(sqlite3.connect(paths.database)) as connection:
            assert connection.execute("PRAGMA user_version").fetchone() == (0,)
    finally:
        release.set()
        confirmation.join(timeout=3)
        if closer.ident is not None:
            closer.join(timeout=3)
        backend.close()
