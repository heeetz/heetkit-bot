"""Tests for the desktop host bridge without opening a native window."""

import asyncio
import logging
import subprocess
import sys
import threading
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast

import pytest

from app.commands.registry import CommandRegistry
from app.app_settings import (
    AISettings,
    AppSettings,
    AppSettingsStore,
    StartupSettings,
    TwitchSettings,
)
from app.config.settings import Settings
from app.container import Application
from app.credentials import CredentialStatus
from app.runtime_paths import DATA_DIR_ENV
from app.runtime_state import RuntimeState
from app.twitch.client import OAUTH_REDIRECT_URI
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.utils.logging import RecentLogBuffer, RecentLogHandler
from app.webview_host import (
    AsyncioBackendHost,
    DesktopAlreadyRunningError,
    DesktopController,
    FRONTEND_OPERATIONS,
    WebUIBridge,
    apply_ai_app_settings,
    apply_twitch_app_settings,
    desktop_instance_guard,
    expose_frontend_operations,
    main,
    resolve_auto_start,
    resolve_frontend_url,
)


def complete_bridge_coroutine(coroutine) -> Future:
    future: Future = Future()
    try:
        future.set_result(asyncio.run(coroutine))
    except BaseException as error:
        future.set_exception(error)
    return future


def test_desktop_instance_guard_blocks_other_process_and_releases(tmp_path) -> None:
    settings_path = tmp_path / "data" / "app_settings.json"
    probe = (
        "import sys; from pathlib import Path; "
        "from app.webview_host import DesktopAlreadyRunningError, desktop_instance_guard; "
        "path = Path(sys.argv[1]); "
        "\ntry:\n"
        "    with desktop_instance_guard(path): pass\n"
        "except DesktopAlreadyRunningError:\n"
        "    sys.exit(2)\n"
    )

    with desktop_instance_guard(settings_path):
        blocked = subprocess.run(
            [sys.executable, "-c", probe, str(settings_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert blocked.returncode == 2, blocked.stderr
        assert not settings_path.exists()
        if sys.platform == "win32":
            assert not settings_path.parent.exists()
        else:
            assert (settings_path.parent / ".desktop-instance.lock").exists()

    permitted = subprocess.run(
        [sys.executable, "-c", probe, str(settings_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert permitted.returncode == 0, permitted.stderr


def test_duplicate_desktop_launch_fails_before_loading_local_state(
    monkeypatch, tmp_path, capsys,
) -> None:
    settings_path = tmp_path / "config" / "app_settings.json"
    notices: list[str] = []
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.webview_host.notify_existing_desktop", notices.append)
    monkeypatch.setattr(
        "app.webview_host.load_settings_with_credentials",
        lambda: pytest.fail("duplicate launch loaded local settings"),
    )
    monkeypatch.setattr(sys, "argv", ["heetkit", "--dev-url", "http://localhost:5173"])

    with desktop_instance_guard(settings_path):
        with pytest.raises(SystemExit) as exit_info:
            main()

    assert exit_info.value.code == 1
    assert len(notices) == 1
    assert "already running" in notices[0]
    assert "already running" in capsys.readouterr().err


def test_default_brand_migration_refuses_a_running_former_desktop(monkeypatch, tmp_path):
    from app import runtime_paths

    monkeypatch.delenv(runtime_paths.DATA_DIR_ENV, raising=False)
    monkeypatch.delenv(runtime_paths.LEGACY_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(runtime_paths, "user_data_path", lambda name, **kwargs: tmp_path / name)
    former = tmp_path / runtime_paths.LEGACY_APP_NAME
    former.mkdir()
    monkeypatch.setattr("app.webview_host.notify_existing_desktop", lambda message: None)
    monkeypatch.setattr("app.webview_host.load_settings_with_credentials", lambda: pytest.fail("loaded state while former desktop was running"))
    monkeypatch.setattr(sys, "argv", ["heetkit", "--stopped"])
    with desktop_instance_guard(former / "config" / "app_settings.json", legacy_identity=True):
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
    assert not (tmp_path / "HeetKit" / ".heetkit-migration-v1").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="POSIX reuses the same advisory profile lock")
def test_explicit_profile_migration_refuses_former_windows_mutex(monkeypatch, tmp_path):
    root = tmp_path / "explicit"
    monkeypatch.setenv(DATA_DIR_ENV, str(root))
    monkeypatch.setattr("app.webview_host.notify_existing_desktop", lambda message: None)
    monkeypatch.setattr("app.webview_host.load_settings_with_credentials", lambda: pytest.fail("loaded an in-use explicit profile"))
    monkeypatch.setattr(sys, "argv", ["heetkit", "--data-dir", str(root)])
    with desktop_instance_guard(root / "config" / "app_settings.json", legacy_identity=True):
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
    assert not (root / ".heetkit-migration-v1").exists()


def test_configuration_check_does_not_acquire_desktop_instance_guard(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["heetkit", "--check", "--dev-url", "http://localhost:5173"])
    monkeypatch.setattr(
        "app.webview_host.desktop_instance_guard",
        lambda path: pytest.fail("--check acquired the desktop instance guard"),
    )
    monkeypatch.setattr(
        "app.webview_host.load_settings_with_credentials",
        lambda *args: (SimpleNamespace(log_level="INFO"), None),
    )
    monkeypatch.setattr(
        "app.webview_host.prepare_runtime_data",
        lambda *args: pytest.fail("--check migrated local state"),
    )
    monkeypatch.setattr("app.webview_host.configure_logging", lambda level: None)

    main()


class FakeHostApplication:
    def __init__(self, *, startup_error: Exception | None = None) -> None:
        self.services = SimpleNamespace(
            runtime_state=SimpleNamespace(set_bot_running=lambda running: None)
        )
        self.startup_error = startup_error
        self.startup_calls = 0
        self.shutdown_calls = 0

    async def startup(self) -> None:
        self.startup_calls += 1
        if self.startup_error is not None:
            raise self.startup_error

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


class BlockingShutdownApplication(FakeHostApplication):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_started = threading.Event()
        self.release_shutdown = threading.Event()

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.shutdown_started.set()
        self.release_shutdown.wait()


def build_backend_host(monkeypatch, application) -> AsyncioBackendHost:
    monkeypatch.setattr(
        "app.webview_host.build_application",
        lambda settings: cast(Application, application),
    )
    return AsyncioBackendHost(cast(Settings, SimpleNamespace()))


def test_backend_host_closes_orderly_once(monkeypatch) -> None:
    application = FakeHostApplication()
    backend = build_backend_host(monkeypatch, application)

    backend.start(timeout=1)
    thread = backend._thread
    assert thread is not None
    assert thread.daemon is True

    backend.close(timeout=1, force_timeout=0.2)
    backend.close(timeout=1, force_timeout=0.2)

    assert application.startup_calls == 1
    assert application.shutdown_calls == 1
    assert not thread.is_alive()


def test_backend_host_cleans_up_after_startup_failure(monkeypatch) -> None:
    application = FakeHostApplication(startup_error=RuntimeError("startup failed"))
    backend = build_backend_host(monkeypatch, application)

    with pytest.raises(RuntimeError, match="Desktop backend startup failed"):
        backend.start(timeout=1)

    thread = backend._thread
    assert thread is not None
    thread.join(timeout=1)
    backend.close(timeout=0.1, force_timeout=0.1)

    assert application.startup_calls == 1
    assert application.shutdown_calls == 1
    assert not thread.is_alive()


def test_backend_host_timeout_uses_bounded_degraded_shutdown(
    monkeypatch,
    caplog,
) -> None:
    application = BlockingShutdownApplication()
    backend = build_backend_host(monkeypatch, application)
    backend.start(timeout=1)
    thread = backend._thread
    assert thread is not None

    with caplog.at_level(logging.ERROR, logger="app.webview"):
        with pytest.raises(TimeoutError, match="forced cleanup"):
            backend.close(timeout=0.05, force_timeout=0.05)

    assert application.shutdown_started.is_set()
    assert application.shutdown_calls == 1
    assert thread.is_alive()
    assert thread.daemon is True
    assert "cancelling pending asyncio work" in caplog.text
    assert "daemon thread will not block process exit" in caplog.text

    application.release_shutdown.set()
    thread.join(timeout=1)
    backend.close(timeout=0.1, force_timeout=0.1)

    assert not thread.is_alive()
    assert application.shutdown_calls == 1


def test_bridge_reads_shared_runtime_status() -> None:
    runtime_state = SimpleNamespace(
        status=lambda: (True, 42), twitch_connected=True, twitch_connection_state="connected"
    )
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(twitch_channel="channel", twitch_bot_username="bot"),
    )
    backend = SimpleNamespace(application=application)

    result = WebUIBridge(cast(AsyncioBackendHost, backend)).get_app_status()

    assert result == {
        "running": True,
        "twitch_connected": True,
        "twitch_connection_state": "connected",
        "uptime_seconds": 42,
        "channel": "channel",
        "account": "bot",
    }


def test_bridge_exposes_about_metadata_and_fixed_external_destinations(monkeypatch) -> None:
    opened: list[tuple[str, int]] = []

    def fake_open(url: str, *, new: int) -> bool:
        opened.append((url, new))
        return True

    monkeypatch.setattr("app.webview_host.webbrowser.open", fake_open)
    monkeypatch.setattr("app.webview_host.VERSION", "9.8.7")
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace()))

    about = bridge.get_about_info()

    assert about["application_name"] == "HeetKit"
    assert about["application_subtitle"] == "Desktop control center for Twitch chat"
    assert about["author_twitch"] == "@heet_ok"
    assert about["version"] == "9.8.7"
    assert about["author"] == "heeetz"
    assert about["discord_contact"] == "de.tected"
    assert about["license_name"] == "Apache-2.0"
    for destination in ("repository", "license", "third_party_notices", "twitch_developer_console", "author_twitch"):
        assert bridge.open_external_link(destination) == {"ok": True}
    assert opened == [
        ("https://github.com/heeetz/twitch-bot", 2),
        ("https://github.com/heeetz/twitch-bot/blob/main/LICENSE", 2),
        ("https://github.com/heeetz/twitch-bot/blob/main/THIRD_PARTY_NOTICES.md", 2),
        ("https://dev.twitch.tv/console/apps", 2),
        ("https://www.twitch.tv/heet_ok", 2),
    ]
    assert bridge.open_external_link("https://example.com") == {
        "ok": False,
        "error": "That external link is not available.",
    }


def test_bridge_profile_location_uses_default_runtime_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    root = tmp_path / "default profile"
    monkeypatch.setattr("app.runtime_paths.user_data_path", lambda *args, **kwargs: root)
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace()))

    assert bridge.get_profile_info() == {"path": str(root.resolve())}
    assert not root.exists()  # Reading diagnostics must not create or migrate data.


def test_desktop_cli_profile_location_uses_data_dir_over_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "environment profile"))
    root = tmp_path / "CLI profile"
    settings = Settings()
    monkeypatch.setattr(sys, "argv", [
        "heetkit", "--data-dir", root.name, "--stopped", "--dev-url", "http://localhost:5173",
    ])
    monkeypatch.setattr("app.webview_host.load_settings_with_credentials", lambda: (settings, None))
    monkeypatch.setattr("app.webview_host.configure_logging", lambda level: None)
    opened = []
    monkeypatch.setattr("app.webview_host.os.startfile", lambda *args: opened.append(args), raising=False)
    monkeypatch.setattr("app.webview_host.subprocess.run", lambda command, **kwargs: opened.append(tuple(command)))

    def capture_desktop(settings, frontend_url, **kwargs):
        bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace()))
        assert bridge.get_profile_info() == {"path": str(root.resolve())}
        assert bridge.open_profile_folder() == {"ok": True}
        assert settings.twitch_token_file == str(root / "auth" / "twitchio_tokens.json")
        assert kwargs["auto_start"] is False

    monkeypatch.setattr("app.webview_host.run_desktop_host", capture_desktop)
    main()
    assert len(opened) == 1
    assert str(root.resolve()) in opened[0]
    assert not (tmp_path / "environment profile").exists()


@pytest.mark.parametrize("platform,launcher", [("win32", None), ("darwin", "open"), ("linux", "xdg-open")])
def test_bridge_opens_captured_selected_profile(tmp_path, monkeypatch, platform, launcher) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "Selected profile & 日本語"
    root.mkdir()
    monkeypatch.setenv(DATA_DIR_ENV, root.name)
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace()))
    # An environment/cwd change after startup must not select another profile.
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "other"))
    monkeypatch.chdir(root)
    assert bridge.get_profile_info() == {"path": str(root.resolve())}
    monkeypatch.setattr("app.webview_host.sys.platform", platform)
    calls = []
    monkeypatch.setattr("app.webview_host.os.startfile", lambda *args: calls.append(args), raising=False)
    monkeypatch.setattr("app.webview_host.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert bridge.open_profile_folder() == {"ok": True}
    if launcher is None:
        assert calls == [(str(root.resolve()), "explore")]
    else:
        assert calls == [(([launcher, str(root.resolve())],), {
            "check": True, "timeout": 5, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
        })]
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("as_file", [False, True])
def test_bridge_refuses_to_open_missing_or_replaced_profile(tmp_path, monkeypatch, as_file) -> None:
    root = tmp_path / "missing profile"
    if as_file:
        root.write_text("synthetic data", encoding="utf-8")
    monkeypatch.setenv(DATA_DIR_ENV, str(root))
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace()))
    monkeypatch.setattr("app.webview_host.os.startfile", lambda *args: pytest.fail("opened a non-directory"), raising=False)
    monkeypatch.setattr("app.webview_host.subprocess.run", lambda *args, **kwargs: pytest.fail("opened a non-directory"))

    assert bridge.open_profile_folder() == {
        "ok": False, "error": "The profile folder is no longer available.",
    }


@pytest.mark.parametrize("platform,error", [
    ("win32", OSError("synthetic private path")),
    ("linux", FileNotFoundError("xdg-open")),
    ("linux", subprocess.CalledProcessError(1, "xdg-open")),
    ("darwin", subprocess.TimeoutExpired("open", 5)),
])
def test_bridge_reports_file_manager_failure_without_private_details(tmp_path, monkeypatch, caplog, platform, error) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace()))
    monkeypatch.setattr("app.webview_host.sys.platform", platform)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("app.webview_host.os.startfile", fail, raising=False)
    monkeypatch.setattr("app.webview_host.subprocess.run", fail)
    assert bridge.open_profile_folder() == {
        "ok": False, "error": "Could not open the profile folder in the system file manager.",
    }
    assert "synthetic private path" not in caplog.text
    assert str(tmp_path) not in caplog.text


def twitch_authorization_bridge(tmp_path, *, running=True, state="auth_required", **overrides):
    settings = Settings(
        twitch_client_id="synthetic-client",
        twitch_client_secret="synthetic-secret",
        twitch_bot_user_id="100",
        twitch_bot_username="testbot",
        twitch_channel_user_id="200",
        twitch_channel="testchannel",
        twitch_token_file=str(tmp_path / "tokens.json"),
    )
    for name, value in overrides.items():
        setattr(settings, name, value)
    runtime_state = RuntimeState()
    runtime_state.set_bot_running(running)
    runtime_state.set_twitch_connection_state(state)
    async def begin_authorization():
        return "https://id.twitch.tv/oauth2/authorize?state=synthetic-desktop-attempt"

    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state, twitch=SimpleNamespace(begin_authorization=begin_authorization)), settings=settings,
    )
    return WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace(application=application, submit=complete_bridge_coroutine)),
        app_settings=AppSettingsStore(tmp_path / "app_settings.json"),
    )


def test_twitch_authorization_opens_only_on_explicit_action(monkeypatch, tmp_path) -> None:
    opened = []
    monkeypatch.setattr(
        "app.webview_host.webbrowser.open",
        lambda url, *, new: opened.append((url, new)) or True,
    )
    bridge = twitch_authorization_bridge(tmp_path)

    assert bridge.get_app_status()["twitch_connection_state"] == "auth_required"
    assert bridge.get_twitch_settings()["settings"]["oauth_callback_url"] == OAUTH_REDIRECT_URI
    assert opened == []
    assert bridge.open_external_link("twitch_authorization") == {"ok": True}
    assert opened == [("https://id.twitch.tv/oauth2/authorize?state=synthetic-desktop-attempt", 2)]


@pytest.mark.parametrize("running,state", [
    (False, "stopped"), (False, "auth_required"), (True, "connecting"),
    (True, "connected"), (True, "reconnecting"), (True, "failed"),
])
def test_twitch_authorization_requires_a_running_auth_required_session(
    monkeypatch, tmp_path, running, state,
) -> None:
    monkeypatch.setattr(
        "app.webview_host.webbrowser.open", lambda *args, **kwargs: pytest.fail("opened browser"),
    )
    bridge = twitch_authorization_bridge(tmp_path, running=running, state=state)
    assert bridge.open_external_link("twitch_authorization")["ok"] is False


@pytest.mark.parametrize("missing", ["twitch_client_id", "twitch_bot_user_id", "twitch_client_secret"])
def test_twitch_authorization_requires_configured_identity_and_secret(
    monkeypatch, tmp_path, missing,
) -> None:
    monkeypatch.setattr(
        "app.webview_host.webbrowser.open", lambda *args, **kwargs: pytest.fail("opened browser"),
    )
    bridge = twitch_authorization_bridge(tmp_path, **{missing: None if missing.endswith("secret") else ""})
    result = bridge.open_external_link("twitch_authorization")
    assert result["ok"] is False
    assert missing.upper() in result["error"]


def test_twitch_authorization_rejects_pending_identity_changes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "app.webview_host.webbrowser.open", lambda *args, **kwargs: pytest.fail("opened browser"),
    )
    bridge = twitch_authorization_bridge(tmp_path)
    saved = bridge.update_twitch_settings(
        "testchannel", "200", client_id="different-client", bot_username="testbot", bot_user_id="100",
    )
    assert saved["ok"] is True
    assert saved["requires_restart"] is True
    result = bridge.open_external_link("twitch_authorization")
    assert result["ok"] is False
    assert "Restart" in result["error"]


@pytest.mark.parametrize("destination", ["twitch_developer_console", "twitch_authorization"])
@pytest.mark.parametrize("raises", [False, True])
def test_twitch_external_actions_report_browser_failure(
    monkeypatch, tmp_path, destination, raises,
) -> None:
    def failed_open(*args, **kwargs):
        if raises:
            raise OSError("synthetic browser failure")
        return False

    monkeypatch.setattr("app.webview_host.webbrowser.open", failed_open)
    bridge = twitch_authorization_bridge(tmp_path)
    assert bridge.open_external_link(destination) == {
        "ok": False, "error": "Could not open the external link.",
    }


def test_twitch_app_settings_override_environment_defaults() -> None:
    settings = Settings(
        _env_file=None,
        twitch_client_id="client-id",
        twitch_client_secret="client-secret",
        twitch_bot_user_id="100",
        twitch_bot_username="testbot",
        twitch_channel_user_id="200",
        twitch_channel="environment-channel",
    )

    effective = apply_twitch_app_settings(
        settings,
        AppSettings(
            twitch=TwitchSettings(
                channel="local-channel",
                channel_user_id="300",
            )
        ),
    )

    assert effective.twitch_channel == "local-channel"
    assert effective.twitch_channel_user_id == "300"
    assert settings.twitch_channel == "environment-channel"


def test_ai_app_settings_override_environment_model_defaults() -> None:
    settings = Settings(
        _env_file=None,
        twitch_client_id="client-id",
        twitch_client_secret="client-secret",
        twitch_bot_user_id="100",
        twitch_bot_username="testbot",
        twitch_channel_user_id="200",
        twitch_channel="channel",
        gemini_model="gemini-environment",
        gemini_fallback_model="gemini-environment-fallback",
    )

    effective = apply_ai_app_settings(
        settings,
        AppSettings(
            ai=AISettings(
                selected_model="gemini-local",
                fallback_model="gemini-local-fallback",
            )
        ),
    )

    assert effective.gemini_model == "gemini-local"
    assert effective.gemini_fallback_model == "gemini-local-fallback"
    assert settings.gemini_model == "gemini-environment"


def test_saved_auto_start_defaults_off_and_accepts_explicit_override() -> None:
    defaults = AppSettings()
    enabled = AppSettings(startup=StartupSettings(auto_start_bot=True))

    assert resolve_auto_start(defaults, None) is False
    assert resolve_auto_start(enabled, None) is True
    assert resolve_auto_start(enabled, False) is False
    assert resolve_auto_start(defaults, True) is True


def test_bridge_exposes_and_updates_ai_provider_settings(tmp_path) -> None:
    settings = SimpleNamespace(
        gemini_model="gemini-selected",
        gemini_fallback_model="gemini-fallback",
    )
    application = SimpleNamespace(
        settings=settings,
        services=SimpleNamespace(ai=SimpleNamespace()),
    )
    credential_manager = SimpleNamespace(
        statuses=lambda: (
            CredentialStatus(
                name="gemini_api_key",
                label="Gemini API key",
                configured=True,
                source="environment",
                secure_storage_available=True,
            ),
        )
    )
    store = AppSettingsStore(tmp_path / "app_settings.json")
    bridge = WebUIBridge(
        cast(
            AsyncioBackendHost,
            SimpleNamespace(
                application=application,
                submit=complete_bridge_coroutine,
            ),
        ),
        app_settings=store,
        credential_manager=credential_manager,
    )

    result = bridge.get_ai_provider_settings()
    assert result["ok"] is True
    assert result["settings"]["provider"] == "Google Gemini"
    assert result["settings"]["selected_model"] == "gemini-selected"
    assert result["settings"]["credential"]["configured"] is True
    assert "value" not in result["settings"]["credential"]

    assert bridge.update_ai_provider_settings("gemini-new", "gemini-safe") == {
        "ok": True
    }
    assert settings.gemini_model == "gemini-new"
    assert settings.gemini_fallback_model == "gemini-safe"
    assert store.snapshot().ai == AISettings(
        selected_model="gemini-new",
        fallback_model="gemini-safe",
    )


def test_bridge_discovers_models_on_the_existing_backend_loop() -> None:
    class FakeAI:
        async def discover_models(self) -> list[str]:
            return ["gemini-discovered"]

    class FakeBackend:
        application = SimpleNamespace(services=SimpleNamespace(ai=FakeAI()))

        def submit(self, coroutine):
            future: Future[list[str]] = Future()
            future.set_result(asyncio.run(coroutine))
            return future

    bridge = WebUIBridge(cast(AsyncioBackendHost, FakeBackend()))

    assert bridge.discover_gemini_models() == {
        "ok": True,
        "models": ["gemini-discovered"],
    }


def test_bridge_timeout_cancels_pending_backend_operation(
    monkeypatch,
    caplog,
) -> None:
    class FakeBotRuntime:
        async def start_bot(self) -> bool:
            return True

    class PendingBackend:
        def __init__(self) -> None:
            self.bot_runtime = FakeBotRuntime()
            self.future: Future[bool] = Future()

        def submit(self, coroutine):
            coroutine.close()
            return self.future

    backend = PendingBackend()
    bridge = WebUIBridge(cast(AsyncioBackendHost, backend))
    monkeypatch.setattr("app.webview_host.BRIDGE_BOT_START_TIMEOUT_SECONDS", 0.01)

    with caplog.at_level(logging.ERROR, logger="app.webview.bridge"):
        result = bridge.start_bot()

    assert result == {
        "ok": False,
        "changed": False,
        "error": "Starting the bot timed out. Check Logs for details.",
    }
    assert backend.future.cancelled()
    assert "operation=start_bot" in caplog.text
    assert "cancellation_requested=True" in caplog.text


def test_bridge_observes_backend_completion_after_timeout(
    monkeypatch,
    caplog,
) -> None:
    class UncancellableFuture(Future[bool]):
        def cancel(self) -> bool:
            return False

    class FakeBotRuntime:
        async def start_bot(self) -> bool:
            return True

    class LateBackend:
        def __init__(self) -> None:
            self.bot_runtime = FakeBotRuntime()
            self.future = UncancellableFuture()

        def submit(self, coroutine):
            coroutine.close()
            return self.future

    backend = LateBackend()
    bridge = WebUIBridge(cast(AsyncioBackendHost, backend))
    monkeypatch.setattr("app.webview_host.BRIDGE_BOT_START_TIMEOUT_SECONDS", 0.01)

    with caplog.at_level(logging.WARNING, logger="app.webview.bridge"):
        result = bridge.start_bot()
        backend.future.set_result(True)

    assert result["ok"] is False
    assert "completed after its UI deadline operation=start_bot" in caplog.text


def test_bridge_serializes_persist_and_apply_model_updates() -> None:
    first_started = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()

    class BlockingSettingsStore:
        def __init__(self) -> None:
            self.ai = AISettings()
            self.calls: list[str] = []

        def update_ai_models(self, *, selected_model, fallback_model):
            self.calls.append(selected_model)
            if selected_model == "gemini-first":
                first_started.set()
                assert release_first.wait(timeout=1)
            else:
                second_entered.set()
            self.ai = AISettings(
                selected_model=selected_model,
                fallback_model=fallback_model,
            )
            return AppSettings(ai=self.ai)

    class SerialBackend:
        def __init__(self) -> None:
            self.application = SimpleNamespace(
                settings=SimpleNamespace(
                    gemini_model="gemini-original",
                    gemini_fallback_model="gemini-original-fallback",
                )
            )
            self.executor = ThreadPoolExecutor(max_workers=1)

        def submit(self, coroutine):
            return self.executor.submit(asyncio.run, coroutine)

    store = BlockingSettingsStore()
    backend = SerialBackend()
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, backend),
        app_settings=cast(AppSettingsStore, store),
    )
    results: list[dict[str, object]] = []
    first = threading.Thread(
        target=lambda: results.append(
            bridge.update_ai_provider_settings("gemini-first", "gemini-first-fallback")
        )
    )
    second = threading.Thread(
        target=lambda: results.append(
            bridge.update_ai_provider_settings("gemini-second", "gemini-second-fallback")
        )
    )

    try:
        first.start()
        assert first_started.wait(timeout=1)
        second.start()
        assert not second_entered.wait(timeout=0.05)
        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)
    finally:
        release_first.set()
        backend.executor.shutdown(wait=True)

    assert not first.is_alive()
    assert not second.is_alive()
    assert results == [{"ok": True}, {"ok": True}]
    assert store.calls == ["gemini-first", "gemini-second"]
    assert store.ai == AISettings(
        selected_model="gemini-second",
        fallback_model="gemini-second-fallback",
    )
    assert backend.application.settings.gemini_model == "gemini-second"
    assert (
        backend.application.settings.gemini_fallback_model
        == "gemini-second-fallback"
    )


def test_bridge_exposes_and_saves_non_secret_twitch_settings(tmp_path) -> None:
    token_path = tmp_path / "tokens.json"
    token_path.write_text("{}", encoding="utf-8")
    runtime_state = SimpleNamespace(
        status=lambda: (True, 12),
        twitch_connected=True,
    )
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(
            twitch_channel="environment-channel",
            twitch_channel_user_id="200",
            twitch_bot_username="testbot",
            twitch_bot_user_id="100",
            twitch_token_file=str(token_path),
        ),
    )
    store = AppSettingsStore(tmp_path / "app_settings.json")
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace(application=application)),
        app_settings=store,
    )

    initial = bridge.get_twitch_settings()
    assert initial["settings"] == {
        "target_channel": "environment-channel",
        "target_channel_user_id": "200",
        "active_channel": "environment-channel",
        "active_channel_user_id": "200",
        "presets": [],
        "selected_preset_id": None,
        "active_preset_id": None,
        "requires_reconnect": False,
        "bot_username": "testbot",
        "bot_user_id": "100",
        "client_id": "",
        "requires_restart": False,
        "running": True,
        "connected": True,
        "oauth_token_available": True,
        "oauth_callback_url": OAUTH_REDIRECT_URI,
        "has_local_override": False,
    }
    assert bridge.update_twitch_settings("NewChannel", "300") == {
        "ok": True,
        "requires_reconnect": True,
        "requires_restart": False,
    }
    assert store.snapshot().twitch == TwitchSettings(
        channel="newchannel",
        channel_user_id="300",
    )


def test_bridge_manages_twitch_presets_without_changing_bot_identity(tmp_path) -> None:
    application = SimpleNamespace(
        services=SimpleNamespace(
            runtime_state=SimpleNamespace(
                status=lambda: (True, 12),
                twitch_connected=True,
            )
        ),
        settings=SimpleNamespace(
            twitch_channel="environment-channel",
            twitch_channel_user_id="200",
            twitch_bot_username="fixedbot",
            twitch_bot_user_id="100",
            twitch_token_file=str(tmp_path / "tokens.json"),
        ),
    )
    store = AppSettingsStore(tmp_path / "app_settings.json")
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace(application=application)),
        app_settings=store,
    )

    created = bridge.save_twitch_preset(
        None,
        "Personal test",
        "TestChannel",
        "300",
    )

    assert created["ok"] is True
    assert created["requires_reconnect"] is True
    preset_id = created["preset_id"]
    settings = bridge.get_twitch_settings()["settings"]
    assert settings["selected_preset_id"] == preset_id
    assert settings["active_preset_id"] is None
    assert settings["requires_reconnect"] is True
    assert settings["bot_username"] == "fixedbot"
    assert settings["presets"] == [
        {
            "id": preset_id,
            "display_name": "Personal test",
            "target_channel": "testchannel",
            "target_channel_user_id": "300",
        }
    ]
    assert bridge.update_twitch_settings("testchannel", "300", preset_id) == {
        "ok": True,
        "requires_reconnect": True,
        "requires_restart": False,
    }
    assert bridge.delete_twitch_preset(preset_id) == {"ok": True}
    assert store.snapshot().twitch.presets == ()
    assert application.settings.twitch_bot_username == "fixedbot"


def test_bridge_reconnects_through_existing_bot_runtime(tmp_path) -> None:
    calls: list[tuple[str, str]] = []

    class FakeBotRuntime:
        async def reconnect_twitch(self, *, channel: str, channel_user_id: str) -> bool:
            calls.append((channel, channel_user_id))
            return True

    class FakeBackend:
        def __init__(self) -> None:
            self.application = SimpleNamespace(
                services=SimpleNamespace(
                    runtime_state=SimpleNamespace(
                        status=lambda: (True, 1),
                        twitch_connected=True,
                    )
                ),
                settings=SimpleNamespace(
                    twitch_channel="oldchannel",
                    twitch_channel_user_id="200",
                ),
            )
            self.bot_runtime = FakeBotRuntime()

        def submit(self, coroutine):
            future: Future[bool] = Future()
            future.set_result(asyncio.run(coroutine))
            return future

    store = AppSettingsStore(tmp_path / "app_settings.json")
    store.update_twitch(channel="newchannel", channel_user_id="300")
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, FakeBackend()),
        app_settings=store,
    )

    assert bridge.reconnect_twitch() == {"ok": True, "changed": True}
    assert calls == [("newchannel", "300")]


def test_bridge_gets_commands_from_registry_and_effective_runtime_settings() -> None:
    definition = SimpleNamespace(
        name="erase",
        aliases=("forget",),
        hidden=True,
        requires_ai=False,
    )
    settings = SimpleNamespace(
        enabled=False,
        permission=SimpleNamespace(name="BROADCASTER"),
        cooldown=SimpleNamespace(per_user_seconds=3.0, global_seconds=5.0),
    )
    runtime_state = SimpleNamespace(
        get_command_settings=lambda name: settings,
        get_command_default_settings=lambda name: settings,
        command_settings_are_saved=lambda name: True,
        has_saved_command_override=lambda name: False,
    )
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        registry=SimpleNamespace(definitions=lambda: (definition,)),
        settings=SimpleNamespace(command_prefix="!"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))

    result = bridge.get_commands()

    assert result == {
        "command_prefix": "!",
        "permissions": [
            "USER",
            "SUBSCRIBER",
            "VIP",
            "MODERATOR",
            "BROADCASTER",
        ],
        "commands": [
            {
                "name": "erase",
                "aliases": ["forget"],
                "enabled": False,
                "available": True,
                "unavailable_reason": None,
                "response_pool": None,
                "permission": "BROADCASTER",
                "cooldown": {
                    "per_user_seconds": 3.0,
                    "global_seconds": 5.0,
                },
                "hidden": True,
                "default_settings": {
                    "enabled": False,
                    "permission": "BROADCASTER",
                    "cooldown": {
                        "per_user_seconds": 3.0,
                        "global_seconds": 5.0,
                    },
                },
                "saved": True,
                "has_saved_override": False,
            }
        ],
    }


def build_command_bridge(tmp_path) -> tuple[WebUIBridge, RuntimeState]:
    registry = CommandRegistry()

    @registry.command(
        "ping",
        required_permission=Permission.MODERATOR,
        cooldown=CooldownPolicy(global_seconds=10.0),
    )
    async def ping(context, arguments: str) -> None:
        return None

    runtime_state = RuntimeState(command_settings_path=tmp_path / "command_settings.json")
    runtime_state.configure_commands(registry.definitions())
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        registry=registry,
        settings=SimpleNamespace(command_prefix="!"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))
    return bridge, runtime_state


def test_bridge_applies_command_settings_for_current_runtime(tmp_path) -> None:
    bridge, runtime_state = build_command_bridge(tmp_path)

    result = bridge.apply_command_settings("ping", False, 2, 3.5, "VIP")

    assert result == {"ok": True}
    settings = runtime_state.get_command_settings("ping")
    assert settings.enabled is False
    assert settings.cooldown == CooldownPolicy(2.0, 3.5)
    assert settings.permission is Permission.VIP
    assert runtime_state.command_settings_are_saved("ping") is False


@pytest.mark.parametrize(
    ("enabled", "per_user", "global_value", "permission", "expected_error"),
    [
        ("false", 0, 0, "USER", "Enabled must be a boolean."),
        (True, -1, 0, "USER", "Cooldown values must be non-negative numbers."),
        (True, float("nan"), 0, "USER", "Cooldown values must be non-negative numbers."),
        (True, 0, 0, "OWNER", "Permission must be a valid permission name."),
    ],
)
def test_bridge_rejects_invalid_command_settings(
    tmp_path,
    enabled,
    per_user,
    global_value,
    permission,
    expected_error: str,
) -> None:
    bridge, runtime_state = build_command_bridge(tmp_path)
    original = runtime_state.get_command_settings("ping")

    result = bridge.apply_command_settings(
        "ping",
        enabled,
        per_user,
        global_value,
        permission,
    )

    assert result == {"ok": False, "error": expected_error}
    assert runtime_state.get_command_settings("ping") == original


def test_bridge_saves_and_resets_command_settings(tmp_path) -> None:
    bridge, runtime_state = build_command_bridge(tmp_path)

    assert bridge.save_command_settings("ping", False, 1, 2, "BROADCASTER") == {
        "ok": True
    }
    assert runtime_state.has_saved_command_override("ping") is True
    assert bridge.reset_command_settings("ping") == {"ok": True}
    assert runtime_state.get_command_settings("ping").permission is Permission.MODERATOR
    assert runtime_state.has_saved_command_override("ping") is False


def test_bridge_gets_ai_state_without_exposing_personality_prompts() -> None:
    runtime_state = SimpleNamespace(
        ai_enabled=True,
        ai_memory_enabled=False,
        active_ai_personality="neutral",
        available_personalities=("neutral", "vas"),
    )
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        settings=SimpleNamespace(gemini_model="gemini-test"),
    )
    bridge = WebUIBridge(cast(AsyncioBackendHost, SimpleNamespace(application=application)))

    assert bridge.get_ai_status() == {
        "enabled": True,
        "available": False,
        "memory_enabled": False,
        "active_personality": "neutral",
        "available_personalities": ["neutral", "vas"],
        "model": "gemini-test",
    }


def build_ai_bridge(tmp_path) -> tuple[WebUIBridge, RuntimeState]:
    registry = CommandRegistry()

    @registry.command("ask")
    async def ask(context, arguments: str) -> None:
        return None

    runtime_state = RuntimeState(
        command_settings_path=tmp_path / "command_settings.json",
        personality_settings_path=tmp_path / "personality_settings.json",
    )
    runtime_state.configure_commands(registry.definitions())
    application = SimpleNamespace(
        services=SimpleNamespace(runtime_state=runtime_state),
        registry=registry,
        settings=SimpleNamespace(gemini_model="gemini-test"),
    )
    bridge = WebUIBridge(
        cast(
            AsyncioBackendHost,
            SimpleNamespace(
                application=application,
                submit=complete_bridge_coroutine,
            ),
        )
    )
    return bridge, runtime_state


def test_bridge_exposes_only_personality_specific_editable_prompts(tmp_path) -> None:
    bridge, runtime_state = build_ai_bridge(tmp_path)

    result = bridge.get_personalities()

    assert result["active_personality"] == runtime_state.active_ai_personality
    neutral = next(
        item for item in result["personalities"] if item["name"] == "neutral"
    )
    assert "You are a Twitch chat assistant." not in neutral["prompt"]
    assert neutral["prompt"] == neutral["built_in_prompt"]
    assert neutral["is_builtin"] is True
    assert result["profile_instructions"] == ""
    assert result["profile_instructions_saved"] is True
    from app.config.personalities import build_protected_shared_instructions
    assert result["protected_shared_instructions"] == build_protected_shared_instructions()
    assert not hasattr(bridge, "save_protected_shared_instructions")


def test_bridge_applies_saves_resets_profile_instructions_without_saving_personality(tmp_path, caplog) -> None:
    bridge, state = build_ai_bridge(tmp_path)
    state.create_ai_personality("custom", "Saved style")
    state.save_active_ai_personality("custom")
    state.apply_ai_personality("neutral", "Session style")
    with caplog.at_level(logging.INFO):
        assert bridge.apply_profile_instructions("PRIVATE SAMPLE INSTRUCTIONS") == {"ok": True}
        assert bridge.get_personalities()["profile_instructions"] == "PRIVATE SAMPLE INSTRUCTIONS"
        assert bridge.get_personalities()["profile_instructions_saved"] is False
        assert bridge.save_profile_instructions("Saved profile instructions") == {"ok": True}
        assert bridge.get_personalities()["profile_instructions_saved"] is True
        assert bridge.reset_profile_instructions() == {"ok": True}
    assert "PRIVATE SAMPLE INSTRUCTIONS" not in caplog.text
    assert "Saved profile instructions" not in caplog.text
    restored = RuntimeState(personality_settings_path=tmp_path / "personality_settings.json")
    assert restored.active_ai_personality == "custom"
    assert restored.get_ai_personality_prompt("custom") == "Saved style"
    assert restored.profile_instructions == ""
    assert state.active_ai_personality == "neutral"
    assert state.get_ai_personality_prompt("neutral") == "Session style"


def test_bridge_profile_instructions_failure_retains_state_and_explains_repair(tmp_path) -> None:
    bridge, state = build_ai_bridge(tmp_path)
    state.save_profile_instructions("Saved text")
    assert bridge.apply_profile_instructions(123)["ok"] is False
    assert bridge.save_profile_instructions("x" * 50001)["ok"] is False
    path = tmp_path / "personality_settings.json"
    path.write_bytes(b"{broken")
    for result in (bridge.save_profile_instructions("New text"), bridge.reset_profile_instructions()):
        assert result["ok"] is False
        assert "Quit the app, back up and repair" in result["error"]
        assert state.profile_instructions == "Saved text"
        assert path.read_bytes() == b"{broken"


def test_bridge_applies_saves_and_resets_personality(tmp_path) -> None:
    bridge, runtime_state = build_ai_bridge(tmp_path)

    assert bridge.apply_personality("neutral", "temporary") == {"ok": True}
    assert runtime_state.get_ai_personality_prompt("neutral") == "temporary"
    assert runtime_state.active_ai_personality_is_saved is True
    assert runtime_state.personality_prompt_is_saved("neutral") is False

    assert bridge.save_personality("neutral", "saved") == {"ok": True}
    assert runtime_state.get_ai_personality_prompt("neutral") == "saved"
    assert runtime_state.has_saved_personality_override("neutral") is True

    assert bridge.reset_personality("neutral") == {"ok": True}
    assert runtime_state.has_saved_personality_override("neutral") is False
    assert runtime_state.get_ai_personality_prompt("neutral") == (
        runtime_state.get_builtin_ai_personality_prompt("neutral")
    )


def test_bridge_manages_custom_personalities_and_activation_independently(tmp_path) -> None:
    bridge, state = build_ai_bridge(tmp_path)
    state.save_profile_instructions("Kept instructions")
    assert bridge.create_personality(" Custom ", "Exact\n prompt ") == {"ok": True, "name": "Custom"}
    assert state.active_ai_personality == "neutral"
    custom = next(p for p in bridge.get_personalities()["personalities"] if p["name"] == "Custom")
    assert custom["is_builtin"] is False
    assert custom["prompt_saved"] is True
    assert bridge.save_personality("Custom", "Edited") == {"ok": True}
    assert state.active_ai_personality == "neutral"
    assert bridge.set_active_personality("Custom") == {"ok": True}
    assert bridge.rename_personality("Custom", " Renamed ") == {"ok": True, "name": "Renamed"}
    assert state.active_ai_personality == "Renamed"
    assert state.get_ai_personality_prompt("Renamed") == "Edited"
    assert bridge.delete_personality("Renamed") == {"ok": True}
    assert state.active_ai_personality == "neutral"
    restored = RuntimeState(personality_settings_path=tmp_path / "personality_settings.json")
    assert restored.active_ai_personality == "neutral"
    assert restored.profile_instructions == "Kept instructions"
    assert restored.available_personalities == ("neutral",)


def test_bridge_rejects_invalid_collection_operations(tmp_path) -> None:
    bridge, state = build_ai_bridge(tmp_path)
    assert bridge.create_personality("local", "Keep")["ok"]
    before = state.get_personality_settings_snapshot()
    operations = [
        lambda: bridge.create_personality(" local ", "Replace"),
        lambda: bridge.create_personality("neutral", "Replace"),
        lambda: bridge.create_personality(7, "Prompt"),
        lambda: bridge.create_personality("new", None),
        lambda: bridge.rename_personality("local", "neutral"),
        lambda: bridge.rename_personality("neutral", "new"),
        lambda: bridge.rename_personality([], "new"),
        lambda: bridge.delete_personality("neutral"),
        lambda: bridge.delete_personality([]),
        lambda: bridge.delete_personality("missing"),
        lambda: bridge.set_active_personality(None),
        lambda: bridge.set_active_personality("missing"),
        lambda: bridge.save_personality("missing", "No implicit creation"),
    ]
    for action in operations:
        result = action()
        assert result["ok"] is False
        assert result["error"]
        assert state.get_personality_settings_snapshot() == before


def test_bridge_crud_errors_preserve_malformed_profile_and_explain_repair(tmp_path) -> None:
    bridge, state = build_ai_bridge(tmp_path)
    bridge.create_personality("local", "Keep")
    before = state.get_personality_settings_snapshot()
    path = tmp_path / "personality_settings.json"
    path.write_bytes(b"{broken")
    for result in (
        bridge.create_personality("new", "New"),
        bridge.rename_personality("local", "renamed"),
        bridge.delete_personality("local"),
        bridge.set_active_personality("local"),
    ):
        assert result["ok"] is False
        assert "Quit the app, back up and repair" in result["error"]
        assert path.read_bytes() == b"{broken"
        assert state.get_personality_settings_snapshot() == before


def test_bridge_updates_ai_runtime_toggles_with_validation(tmp_path) -> None:
    bridge, runtime_state = build_ai_bridge(tmp_path)

    assert bridge.set_ai_enabled(False) == {"ok": True}
    assert runtime_state.ai_enabled is False
    assert bridge.set_ai_memory_enabled(False) == {"ok": True}
    assert runtime_state.ai_memory_enabled is False
    assert bridge.set_ai_enabled("false") == {
        "ok": False,
        "error": "Enabled must be a boolean.",
    }


def test_bridge_reads_bounded_logs_with_validated_cursor_arguments() -> None:
    log_buffer = RecentLogBuffer(max_entries=2)
    handler = RecentLogHandler(log_buffer)
    for message in ("first", "second", "third"):
        handler.emit(
            logging.LogRecord(
                name="tests.webview",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg=message,
                args=(),
                exc_info=None,
            )
        )
    bridge = WebUIBridge(
        cast(AsyncioBackendHost, SimpleNamespace()),
        log_buffer=log_buffer,
    )

    result = bridge.get_recent_logs(after_id=2, limit=5000)

    assert [entry["message"] for entry in result["entries"]] == ["third"]


def test_production_frontend_requires_a_built_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.webview_host.PACKAGED_FRONTEND",
        SimpleNamespace(is_file=lambda: False),
    )
    monkeypatch.setattr(
        "app.webview_host.FRONTEND_ENTRYPOINT",
        SimpleNamespace(is_file=lambda: False),
    )

    with pytest.raises(FileNotFoundError, match="npm run build"):
        resolve_frontend_url(None)


def test_development_frontend_url_does_not_require_build() -> None:
    assert resolve_frontend_url("http://localhost:5173") == "http://localhost:5173"


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5173", "http://[::1]:5173", "https://localhost:5173",
])
def test_development_frontend_accepts_only_loopback_servers(url) -> None:
    assert resolve_frontend_url(url) == url


@pytest.mark.parametrize("url", [
    "https://example.com", "http://localhost.attacker.test:5173",
    "http://localhost@attacker.test", "http://attacker@localhost:5173",
    "file:///tmp/frontend.html", "javascript:alert(1)", "http://localhost:invalid",
])
def test_remote_or_unsafe_development_frontend_is_rejected(url) -> None:
    with pytest.raises(ValueError, match="loopback"):
        resolve_frontend_url(url)


@pytest.mark.parametrize("frozen", [False, True])
def test_installed_frontend_rejects_development_override(monkeypatch, frozen) -> None:
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if not frozen:
        monkeypatch.setattr("app.webview_host.SOURCE_ROOT", None)
    with pytest.raises(ValueError, match="source checkout"):
        resolve_frontend_url("http://localhost:5173")


def test_remote_development_url_is_rejected_before_loading_credentials(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["heetkit", "--dev-url", "https://attacker.test"])
    monkeypatch.setattr("app.webview_host.load_settings_with_credentials", lambda: pytest.fail("loaded credentials"))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_frontend_allowlist_matches_the_typed_operations() -> None:
    import re

    source = (Path(__file__).parents[1] / "frontend/src/bridge.ts").read_text(encoding="utf-8")
    interface = source.split("interface PythonApi {", 1)[1].split("\n}", 1)[0]
    assert set(FRONTEND_OPERATIONS) == set(re.findall(r"^  (\w+)\(", interface, re.MULTILINE))
    assert len(FRONTEND_OPERATIONS) == len(set(FRONTEND_OPERATIONS))


def test_pywebview_dispatch_cannot_traverse_to_credentials(tmp_path, monkeypatch) -> None:
    from webview.util import js_bridge_call
    from webview.window import Window

    bridge = twitch_authorization_bridge(tmp_path)
    bridge._credential_manager = SimpleNamespace(settings_overrides=lambda: pytest.fail("exposed credentials"))
    bridge.unlisted_secret = lambda: pytest.fail("exposed an unlisted method")
    window = Window("security-test", "Security test", "http://127.0.0.1:54321/index.html")
    returned = []
    monkeypatch.setattr(window, "evaluate_js", returned.append)
    expose_frontend_operations(window, bridge)

    assert window._js_api is None
    assert set(window._functions) == set(FRONTEND_OPERATIONS)
    for path in (
        "_credential_manager.settings_overrides", "_credential_manager.effective_value",
        "_backend.application.settings.gemini_api_key.get_secret_value",
        "get_credentials.__self__._credential_manager.settings_overrides", "unlisted_secret",
    ):
        js_bridge_call(window, path, [], "security-probe")
    assert returned == []


def test_exposed_operations_require_the_initial_frontend_origin(tmp_path, monkeypatch) -> None:
    from webview.window import Window

    bridge = twitch_authorization_bridge(tmp_path)
    calls = []
    monkeypatch.setattr(bridge, "get_credentials", lambda: calls.append("status") or {"ok": True})
    window = Window("origin-test", "Origin test", "http://127.0.0.1:54321/index.html")
    window.real_url = window.original_url
    current_url = window.real_url
    monkeypatch.setattr(window, "get_current_url", lambda: current_url)
    expose_frontend_operations(window, bridge)
    assert window._functions["get_credentials"]()["ok"] is False
    window.events.initialized.set("edgechromium")
    assert window._functions["get_credentials"]() == {"ok": True}
    for current_url in ("https://attacker.test", "http://127.0.0.1:54322/index.html", "file:///tmp/page.html"):
        assert window._functions["get_credentials"]()["ok"] is False
    assert calls == ["status"]


class FakeEvent:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self) -> None:
        self.events = SimpleNamespace(
            closing=FakeEvent(),
            closed=FakeEvent(),
            minimized=FakeEvent(),
        )
        self.hide_calls = 0
        self.show_calls = 0
        self.restore_calls = 0
        self.destroy_calls = 0

    def hide(self) -> None:
        self.hide_calls += 1

    def show(self) -> None:
        self.show_calls += 1

    def restore(self) -> None:
        self.restore_calls += 1

    def destroy(self) -> None:
        self.destroy_calls += 1


class FakeTray:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.update_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def update_menu(self) -> None:
        self.update_calls += 1


class FakeDesktopRuntimeState:
    def __init__(self) -> None:
        self.running = False

    def status(self) -> tuple[bool, int]:
        return self.running, 0


class FakeDesktopBackend:
    def __init__(self) -> None:
        self.runtime_state = FakeDesktopRuntimeState()
        self.application = SimpleNamespace(
            services=SimpleNamespace(runtime_state=self.runtime_state)
        )
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeDesktopBridge:
    def __init__(self, runtime_state: FakeDesktopRuntimeState) -> None:
        self.runtime_state = runtime_state
        self.start_calls = 0
        self.stop_calls = 0

    def start_bot(self) -> dict[str, object]:
        self.start_calls += 1
        self.runtime_state.running = True
        return {"ok": True}

    def stop_bot(self) -> dict[str, object]:
        self.stop_calls += 1
        self.runtime_state.running = False
        return {"ok": True}


def build_desktop_controller(tmp_path):
    backend = FakeDesktopBackend()
    bridge = FakeDesktopBridge(backend.runtime_state)
    tray = FakeTray()
    store = AppSettingsStore(tmp_path / "app_settings.json")
    controller = DesktopController(
        cast(AsyncioBackendHost, backend),
        cast(WebUIBridge, bridge),
        store,
        tray=tray,
    )
    window = FakeWindow()
    controller.bind_window(window)
    return controller, backend, bridge, tray, store, window


def test_desktop_controller_hides_window_for_saved_tray_settings(tmp_path) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )
    store.update_window(
        start_minimized=True,
        minimize_to_tray=True,
        close_to_tray=True,
    )

    controller.start_tray()
    controller.start_tray()
    assert window.events.closing.handlers[0]() is False
    window.events.minimized.handlers[0]()
    controller.open_window()

    assert tray.start_calls == 1
    assert window.hide_calls == 2
    assert window.show_calls == 1
    assert window.restore_calls == 1
    assert backend.close_calls == 0


def test_desktop_controller_keeps_window_reachable_when_tray_fails(tmp_path) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(tmp_path)
    store.update_window(
        start_minimized=True,
        minimize_to_tray=True,
        close_to_tray=True,
    )

    def fail_start() -> None:
        raise RuntimeError("tray backend unavailable")

    tray.start = fail_start
    controller.start_tray()

    assert window.show_calls == 1
    assert window.events.closing.handlers[0]() is None
    window.events.minimized.handlers[0]()
    assert window.hide_calls == 0


def test_desktop_controller_tray_toggles_bot_and_exits_orderly(tmp_path) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )

    controller.toggle_bot()
    controller.toggle_bot()
    controller.exit_application()
    controller.exit_application()
    controller.shutdown()

    assert bridge.start_calls == 1
    assert bridge.stop_calls == 1
    assert tray.update_calls == 2
    assert backend.close_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1


def test_system_tray_toggle_refreshes_menu_once(tmp_path) -> None:
    backend = FakeDesktopBackend()
    bridge = FakeDesktopBridge(backend.runtime_state)
    store = AppSettingsStore(tmp_path / "app_settings.json")
    controller = DesktopController(
        cast(AsyncioBackendHost, backend),
        cast(WebUIBridge, bridge),
        store,
    )
    icon = FakeTray()
    controller._tray._icon = icon

    controller._tray._handle_toggle(None, None)

    assert bridge.start_calls == 1
    assert icon.update_calls == 1


def test_desktop_controller_allows_normal_close_when_setting_is_disabled(
    tmp_path,
) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )

    assert window.events.closing.handlers[0]() is None
    assert window.hide_calls == 0
    window.events.closed.handlers[0]()

    assert backend.close_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 0


def test_desktop_controller_allows_normal_minimize_when_setting_is_disabled(
    tmp_path,
) -> None:
    controller, backend, bridge, tray, store, window = build_desktop_controller(
        tmp_path
    )

    window.events.minimized.handlers[0]()

    assert window.hide_calls == 0
    assert backend.close_calls == 0
