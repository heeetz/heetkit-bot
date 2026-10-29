"""Foreground lifecycle checks with disposable profiles and synthetic Twitch."""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import headless
from app.app_settings import AISettings, AppSettings
from app.config.settings import Settings
from app.desktop_instance import desktop_instance_guard
from app.runtime_paths import RuntimePaths, prepare_runtime_data


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET_FILE", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_FILE", raising=False)
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path / "profile"))
    async def forbidden(*args, **kwargs):
        pytest.fail("Network requests are forbidden in synthetic lifecycle tests")
    monkeypatch.setattr("aiohttp.ClientSession._request", forbidden)
    monkeypatch.setattr("httpx.AsyncClient.send", forbidden)


def settings():
    paths = RuntimePaths.default()
    value = Settings(twitch_client_id="synthetic-client", twitch_client_secret="synthetic-secret",
                     twitch_bot_user_id="100", twitch_bot_username="testbot",
                     twitch_channel_user_id="200", twitch_channel="testchannel")
    prepare_runtime_data(value.twitch_token_file, value.database_url)
    return value


@pytest.fixture
def in_memory_application(monkeypatch):
    """Keep supervisor timing independent of filesystem/SQLite initialization."""
    from app.runtime_state import RuntimeState

    async def noop():
        pass

    application = SimpleNamespace(
        settings=settings(), dispatcher=object(),
        services=SimpleNamespace(runtime_state=RuntimeState()),
        startup=noop, shutdown=noop,
    )
    monkeypatch.setattr(headless, "build_application", lambda _: application)
    return application


@pytest.mark.asyncio
async def test_real_core_restarts_with_saved_profile_and_sqlite(monkeypatch):
    value = settings()
    paths = RuntimePaths.default()
    # Exercise the actual stores, filters, memory preference and persistent users.
    (paths.filters / "blocked_words.txt").write_text("syntheticblocked\n", encoding="utf-8")
    profile = AppSettings(ai=AISettings(memory_enabled=False))
    stop = asyncio.Event()
    sessions = []

    async def session(**kwargs):
        assert kwargs["headless"] is True
        services = kwargs["services"]
        assert not services.runtime_state.ai_memory_enabled
        assert not services.filter_manager.filter_message("syntheticblocked")
        if sessions:
            assert await services.users.get_by_twitch_user_id("300", channel_id=value.twitch_channel_user_id) is not None
        await services.users.upsert_seen(twitch_user_id="300", username="syntheticviewer", channel_id=value.twitch_channel_user_id)
        sessions.append(services)
        services.runtime_state.set_twitch_connection_state("connected")
        await asyncio.sleep(0.15)
        stop.set()
        await kwargs["stop_event"].wait()

    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    for _ in range(2):
        stop.clear()
        assert await headless.run_headless(value, profile, stop, startup_timeout=1, shutdown_timeout=1) == 0
    assert len(sessions) == 2
    assert paths.database.is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["auth_required", "failed", "exception", "ended", "timeout"])
async def test_headless_fails_actionably_without_exposing_payloads(monkeypatch, caplog, failure, in_memory_application):
    async def session(**kwargs):
        if failure == "exception":
            raise RuntimeError("private-request-token-chat-sentinel")
        if failure == "ended":
            return
        if failure != "timeout":
            kwargs["services"].runtime_state.set_twitch_connection_state(failure)
        await kwargs["stop_event"].wait()

    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    startup_timeout = 0.05 if failure == "timeout" else 5
    with caplog.at_level(logging.INFO):
        result = await headless.run_headless(in_memory_application.settings, AppSettings(), asyncio.Event(), startup_timeout=startup_timeout, shutdown_timeout=1)
    assert result == 1
    assert "private-request-token-chat-sentinel" not in caplog.text
    assert "Headless bot stopped" in caplog.text
    if failure == "auth_required":
        assert "authorize" in caplog.text


@pytest.mark.asyncio
async def test_authorization_revoked_after_readiness_exits(monkeypatch):
    async def session(**kwargs):
        state = kwargs["services"].runtime_state
        state.set_twitch_connection_state("connected")
        await asyncio.sleep(0.15)
        state.set_twitch_connection_state("auth_required")
        await kwargs["stop_event"].wait()

    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    assert await headless.run_headless(settings(), AppSettings(), asyncio.Event(), startup_timeout=1, shutdown_timeout=1) == 1


@pytest.mark.asyncio
async def test_connected_service_outlives_startup_deadline(monkeypatch, in_memory_application):
    stop = asyncio.Event()
    async def session(**kwargs):
        kwargs["services"].runtime_state.set_twitch_connection_state("connected")
        await asyncio.sleep(1.2)
        stop.set()
        await kwargs["stop_event"].wait()
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    assert await headless.run_headless(in_memory_application.settings, AppSettings(), stop, startup_timeout=1, shutdown_timeout=1) == 0


@pytest.mark.asyncio
async def test_shutdown_session_failure_returns_nonzero_and_closes_database(monkeypatch):
    stop = asyncio.Event()
    applications = []
    original_build = headless.build_application
    def build(value):
        application = original_build(value)
        applications.append(application)
        return application
    async def session(**kwargs):
        kwargs["services"].runtime_state.set_twitch_connection_state("connected")
        await asyncio.sleep(0.15)
        stop.set()
        await kwargs["stop_event"].wait()
        raise RuntimeError("private failed flush sentinel")
    monkeypatch.setattr(headless, "build_application", build)
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    assert await headless.run_headless(settings(), AppSettings(), stop, startup_timeout=1, shutdown_timeout=1) == 1
    assert applications[0].database._retention_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("startup_failure", [True, False])
async def test_partial_startup_or_slow_stop_still_attempts_application_cleanup(monkeypatch, startup_failure):
    from app.runtime_state import RuntimeState
    calls = []
    application = SimpleNamespace(settings=settings(), dispatcher=object(), services=SimpleNamespace(runtime_state=RuntimeState()))

    async def startup():
        if startup_failure:
            raise RuntimeError("private database details")

    async def shutdown():
        calls.append("closed")

    async def session(**kwargs):
        await asyncio.Event().wait()  # Ignore graceful stop; cancellation is required.

    application.startup, application.shutdown = startup, shutdown
    monkeypatch.setattr(headless, "build_application", lambda _: application)
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", session)
    assert await headless.run_headless(application.settings, AppSettings(), asyncio.Event(), startup_timeout=0.05, shutdown_timeout=0.05) == 1
    assert calls == ["closed"]
    # The foreground main drains leftovers after the bounded shutdown attempt.
    for task in asyncio.all_tasks():
        if task.get_name() == "heetkit-twitch-session":
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cli_uses_environment_without_keyring_applies_saved_settings_and_handles_signals(tmp_path, monkeypatch, signum):
    paths = RuntimePaths.default()
    paths.config.mkdir(parents=True)
    paths.app_settings.write_text(json.dumps({"version": 1, "twitch": {
        "client_id": "saved-client", "bot_user_id": "100", "bot_username": "savedbot",
        "channel_user_id": "200", "channel": "savedchannel"}, "ai": {"memory_enabled": False}}))
    paths.auth.mkdir()
    paths.tokens.write_text("{}")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "private-env-secret")
    monkeypatch.setenv("TWITCH_CLIENT_ID", "overridden-client")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///unrelated-private.db")
    monkeypatch.setattr(headless, "configure_headless_logging", lambda: None)
    handlers = {}
    def register(number, handler):
        handlers[number] = handler
        return signal.SIG_DFL
    monkeypatch.setattr(headless.signal, "signal", register)

    async def run(value, profile, stop, **kwargs):
        assert value.twitch_client_id == "saved-client"
        assert value.twitch_bot_username == "savedbot"
        assert value.twitch_client_secret.get_secret_value() == "private-env-secret"
        assert value.database_url.endswith(str(paths.database))
        assert not profile.ai.memory_enabled
        handlers[signum](signum, None)
        await asyncio.wait_for(stop.wait(), timeout=1)
        return 0
    monkeypatch.setattr(headless, "run_headless", run)
    assert headless.main(["--data-dir", str(paths.root)]) == 0
    assert handlers[signum] == signal.SIG_DFL


def test_cli_locks_profile_before_loading_or_migrating(monkeypatch):
    paths = RuntimePaths.default()
    monkeypatch.setattr(headless, "configure_headless_logging", lambda: None)
    monkeypatch.setattr(headless, "prepare_runtime_data", lambda *args: pytest.fail("Migration ran"))
    with desktop_instance_guard(paths.app_settings):
        assert headless.main([]) == 1
    assert not paths.app_settings.exists()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "301"])
def test_cli_rejects_unbounded_timeouts(value):
    with pytest.raises(SystemExit) as error:
        headless.main(["--startup-timeout", value])
    assert error.value.code == 2


def test_headless_logging_omits_chat_tokens_exceptions_and_identity():
    filter_ = headless.HeadlessLogFilter()
    record = logging.LogRecord("app.twitch", logging.ERROR, "", 0, "private %s", ("token",), (ValueError, ValueError("secret"), None))
    assert not filter_.filter(record)
    record.event_kind = "twitch.failed"
    assert filter_.filter(record)
    assert record.getMessage() == "Twitch lifecycle: twitch.failed"
    assert record.exc_info is None


def test_headless_entry_imports_no_desktop_and_fails_safely_when_unconfigured(tmp_path):
    code = '''
import importlib.abc, sys
class RejectDesktop(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'keyring', 'webview', 'pystray', 'clr', 'tkinter', 'win32api'} or fullname in {'app.webview_host', 'app.system_tray', 'app.windows_runtime'}:
            raise AssertionError('Desktop import: ' + fullname)
sys.meta_path.insert(0, RejectDesktop())
import asyncio
import app.bot_runtime
from app.headless import main, run_headless
from app.app_settings import AppSettings
from app.config.settings import Settings
assert main(sys.argv[1:]) == 1
async def exercise():
    stop = asyncio.Event()
    async def synthetic(**kwargs):
        kwargs['services'].runtime_state.set_twitch_connection_state('connected')
        await asyncio.sleep(0.15)
        stop.set()
        await kwargs['stop_event'].wait()
    app.bot_runtime.run_twitch_bot = synthetic
    settings = Settings(twitch_client_id='synthetic', twitch_client_secret='synthetic', twitch_bot_user_id='100', twitch_bot_username='testbot', twitch_channel_user_id='200', twitch_channel='testchannel')
    # This import-boundary smoke check includes cold real-core/SQLite startup on CI.
    # Tight supervisor deadlines are covered separately with in-memory applications.
    assert await run_headless(settings, AppSettings(), stop, startup_timeout=10, shutdown_timeout=5) == 0
asyncio.run(exercise())
'''
    env = {key: value for key, value in os.environ.items() if key.lower() not in Settings.model_fields}
    env["PYTHON_KEYRING_BACKEND"] = "nonexistent.keyring.Backend"
    process = subprocess.run([sys.executable, "-c", code, "--data-dir", str(tmp_path / "isolated")], env=env, capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert "Missing: TWITCH_CLIENT_ID" in process.stderr
    assert "Desktop import" not in process.stderr
    assert "Traceback" not in process.stderr
