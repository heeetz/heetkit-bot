"""Desktop startup recovery uses disposable profiles, without accounts or GUI launch."""

from contextlib import closing
import asyncio
from datetime import datetime, timezone
import sqlite3

import pytest

from app.app_settings import AppSettings
from app.config.settings import Settings
from app.database import migrations
from app.headless import run_headless
from app.runtime_paths import RuntimePaths
from app.webview_host import AsyncioBackendHost


@pytest.fixture(params=[0, 1])
def legacy_settings(tmp_path, monkeypatch, request):
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
        if request.param == 1:
            connection.execute("CREATE TABLE schema_metadata (name TEXT NOT NULL PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO schema_metadata VALUES ('schema_version', '1')")
            connection.execute("PRAGMA user_version=1")
        connection.commit()
    return Settings(database_url="sqlite+aiosqlite:///" + str(paths.database), twitch_channel="configured_channel",
                    twitch_channel_user_id="200"), paths


def test_desktop_entrypoint_shows_actionable_migration_errors(legacy_settings, monkeypatch, capsys):
    import sys
    from app.webview_host import main
    settings, paths = legacy_settings
    notices = []
    monkeypatch.setattr(sys, "argv", ["heetkit", "--stopped"])
    monkeypatch.setattr("app.webview_host.ensure_windows_runtime", lambda: None)
    monkeypatch.setattr("app.webview_host.load_settings_with_credentials", lambda: (settings, None))
    monkeypatch.setattr("app.webview_host.prepare_runtime_data", lambda database: (str(paths.tokens), database))
    monkeypatch.setattr("app.webview_host.configure_logging", lambda _: None)
    monkeypatch.setattr("app.webview_host.resolve_frontend_url", lambda _: "synthetic-frontend")
    def start(settings, *_, **__):
        backend = AsyncioBackendHost(settings)
        try:
            backend.start()
        finally:
            backend.close()
    monkeypatch.setattr("app.webview_host.run_desktop_host", start)
    original = paths.database.read_bytes()
    monkeypatch.setattr("app.webview_host.notify_existing_desktop", notices.append)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    output = capsys.readouterr().err
    assert "Install HeetKit 1.6 once to update it" in output
    assert "Keep the database and recovery copies" in output
    assert "Traceback" not in output
    assert len(notices) == 1 and "Install HeetKit 1.6 once to update it" in notices[0]
    assert paths.database.read_bytes() == original
    assert not migrations._recovery_paths(paths.database, version=0)[0].exists()


async def test_headless_rejects_unsupported_database_with_update_guidance(legacy_settings, caplog):
    settings, paths = legacy_settings
    original = paths.database.read_bytes()
    with pytest.raises(migrations.DatabaseMigrationError) as error:
        migrations.initialize_schema(paths.database)
    assert error.value.code == "database.update_through_1_6"

    assert await run_headless(settings, AppSettings(), asyncio.Event()) == 1
    assert str(error.value) in caplog.text
    assert paths.database.read_bytes() == original
    assert not migrations._recovery_paths(paths.database, version=0)[0].exists()
