"""Foreground entry point for one preauthorized, profile-owned Twitch bot."""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import signal
import stat
import sys
from contextlib import ExitStack
from pathlib import Path

from app.app_settings import AppSettings, AppSettingsStore
from app.bot_runtime import BotRuntime
from app.config.profile_settings import apply_ai_app_settings, apply_twitch_app_settings
from app.config.settings import Settings, TwitchConfigurationError
from app.container import build_application
from app.desktop_instance import DesktopAlreadyRunningError, desktop_instance_guard
from app.headless_health import HealthFile
from app.operation_policy import OperationPolicy
from app.runtime_paths import DATA_DIR_ENV, RuntimePaths, prepare_runtime_data
from app.utils.logging import OperatorActivityHandler, RecentLogBuffer, PrivacyLogFilter


logger = logging.getLogger("app.headless")
AUTHORIZATION_HELP = (
    "Twitch authorization is missing, expired or revoked. Use Connect Twitch in authenticated "
    "Server Settings, or stop this process and authorize the matching bot/application in "
    "Desktop using this profile, then stop Desktop before restarting headless."
)


class HeadlessError(RuntimeError):
    """A fixed, safe operator diagnostic, with no provider payload attached."""


def secret_file_settings() -> dict[str, str]:
    """Read only supported secret files, bounded and without environment publication."""
    values = {}
    for name in ("TWITCH_CLIENT_SECRET", "GEMINI_API_KEY"):
        filename = os.environ.get(name + "_FILE")
        if not filename:
            continue
        if os.environ.get(name, "").strip():
            raise HeadlessError(f"Set only {name} or {name}_FILE, then restart.")
        try:
            descriptor = os.open(filename, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError
                content = source.read(16385)
            if len(content) > 16384:
                raise ValueError
            secret = content.decode("utf-8").strip()
            if any(character in secret for character in ("\x00", "\r", "\n")):
                raise ValueError
        except (OSError, ValueError):
            raise HeadlessError(f"Cannot read {name}_FILE. Use a readable regular UTF-8 secret file of at most 16 KiB.") from None
        if secret:
            values[name.lower()] = secret
    return values


class HeadlessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "app.headless":
            return True
        kind = getattr(record, "event_kind", None)
        if kind in {
            "twitch.subscribe", "twitch.connected", "twitch.recovered", "twitch.disconnected",
            "twitch.auth_required", "twitch.failed", "twitch.shutdown",
            "operation.mode", "operation.stream", "operation.poll", "operation.failed",
        }:
            # Render only application-owned lifecycle codes, never event payloads,
            # identities, chat text, URLs, exception text or traceback locals.
            record.msg, record.args = "Twitch lifecycle: %s", (kind,)
            record.exc_info = record.exc_text = record.stack_info = None
            return True
        return False


def configure_headless_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(HeadlessLogFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("twitchio").setLevel(logging.CRITICAL + 1)


async def _cancel_task(task: asyncio.Task, *, grace: float = 1.0) -> bool:
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=grace)
    if task in done:
        # Retrieve failures without rendering their potentially sensitive text.
        if not task.cancelled():
            task.exception()
        return True
    return False


async def run_headless(
    settings: Settings,
    profile: AppSettings,
    stop: asyncio.Event,
    *,
    startup_timeout: float = 60.0,
    shutdown_timeout: float = 20.0,
    health: HealthFile | None = None,
    management_config=None,
    credentials=None,
) -> int:
    """Supervise the existing runtime; TwitchIO continues to own network retries."""
    application = build_application(settings)
    application.services.runtime_state.set_ai_memory_enabled(profile.ai.memory_enabled)
    runtime = BotRuntime(application, logging.getLogger("app.headless.twitch"), headless=True)
    state = application.services.runtime_state
    health = health or HealthFile(None)
    ready = asyncio.Event()
    management = None
    recent_handler = None
    store = AppSettingsStore(RuntimePaths.default().app_settings)
    policy = OperationPolicy(runtime, store)

    async def serve() -> None:
        nonlocal management, recent_handler
        deadline = asyncio.get_running_loop().time() + startup_timeout
        # The outer wait also bounds database/application startup.
        await runtime.startup()
        if management_config is not None:
            from app.management_api import ManagementAPI
            buffer = RecentLogBuffer()
            recent_handler = OperatorActivityHandler(buffer)
            recent_handler.addFilter(PrivacyLogFilter())
            logging.getLogger().addHandler(recent_handler)
            management = ManagementAPI(runtime, management_config, buffer, policy=policy, app_settings=store, credentials=credentials)
            await management.start()
            ready.set()  # Browser management is independent of Twitch readiness.
        await policy.start()
        waiter = None
        generation = 0
        connected = False
        try:
            while True:
                if runtime.generation != generation:
                    if waiter is not None:
                        waiter.cancel()
                        await asyncio.gather(waiter, return_exceptions=True)
                    waiter = asyncio.create_task(runtime.wait_until_stopped())
                    generation = runtime.generation
                    connected = False
                    deadline = asyncio.get_running_loop().time() + startup_timeout
                if not policy.desired_running:
                    if policy.error and management is None:
                        raise HeadlessError("Twitch session failed. Check configuration, authorization and private storage.")
                    ready.set()
                    health.update("failed" if policy.error else "idle")
                    await asyncio.sleep(0.1)
                    continue
                if policy.pending:
                    health.update("starting")
                    await asyncio.sleep(0.1)
                    continue
                health.update(state.twitch_connection_state)
                failure = None
                if state.twitch_connection_state == "auth_required":
                    failure = AUTHORIZATION_HELP
                elif state.twitch_connection_state == "failed":
                    failure = "Twitch session failed. Check authorization, network and writable private profile storage, then restart."
                elif waiter is not None and waiter.done():
                    failure = "Twitch session ended unexpectedly. Check configuration and restart."
                    # Retrieve but never expose potentially private exceptions.
                    await asyncio.gather(waiter, return_exceptions=True)
                if state.twitch_connection_state == "connected" and not connected:
                    connected = True
                    ready.set()
                    logger.info("Headless bot connected; waiting for SIGINT or SIGTERM.")
                if not connected and asyncio.get_running_loop().time() >= deadline:
                    failure = "Twitch startup timed out. Check authorization, configuration and network, then restart."
                if failure is not None:
                    if management is None:
                        raise HeadlessError(failure)
                    logger.error("%s", failure)
                    policy.connection_failed()
                await asyncio.sleep(0.1)
        finally:
            # Do not propagate cancellation through this observer into the session;
            # runtime.shutdown first gets a chance to flush tokens gracefully.
            if waiter is not None:
                if not waiter.done():
                    waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)

    worker = asyncio.create_task(serve(), name="heetkit-headless-supervisor")
    stop_waiter = asyncio.create_task(stop.wait())
    ready_waiter = asyncio.create_task(ready.wait())
    result = 0
    try:
        done, _ = await asyncio.wait({worker, stop_waiter, ready_waiter}, timeout=startup_timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise HeadlessError("Headless startup timed out. Check database, authorization and network, then restart.")
        if ready_waiter in done and stop_waiter not in done and worker not in done:
            done, _ = await asyncio.wait({worker, stop_waiter}, return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            await worker
        elif stop_waiter not in done:
            raise HeadlessError("Headless supervision stopped unexpectedly.")
    except HeadlessError as error:
        logger.error("%s", error)
        result = 1
    except Exception as error:
        logger.error("Headless operation failed (%s). Check configuration, authorization and private profile storage.", type(error).__name__)
        result = 1
    finally:
        stop_waiter.cancel()
        ready_waiter.cancel()
        await asyncio.gather(stop_waiter, ready_waiter, return_exceptions=True)
        # Stop the supervisor without canceling the Twitch session it observes.
        if not await _cancel_task(worker):
            logger.error("Startup did not respond to cancellation.")
            result = 1
        if management is not None:
            api_cleanup = asyncio.create_task(management.close())
            done, _ = await asyncio.wait({api_cleanup}, timeout=5.0)
            if api_cleanup not in done:
                logger.error("Management shutdown timed out; canceling remaining requests.")
                await _cancel_task(api_cleanup)
                result = 1
            elif api_cleanup.cancelled() or api_cleanup.exception() is not None:
                logger.error("Management cleanup failed; continuing application shutdown.")
                result = 1
        if recent_handler is not None:
            logging.getLogger().removeHandler(recent_handler)
        async def shutdown():
            try:
                await policy.close()
            finally:
                await runtime.shutdown()
        runtime.request_stop()
        cleanup = asyncio.create_task(shutdown())
        done, _ = await asyncio.wait({cleanup}, timeout=shutdown_timeout)
        if cleanup not in done:
            logger.error("Graceful shutdown timed out; canceling remaining work.")
            await _cancel_task(cleanup)
            result = 1
        elif cleanup.cancelled() or cleanup.exception() is not None:
            logger.error("Application cleanup failed; verify private profile storage before restarting.")
            result = 1
        logger.info("Headless bot stopped.")
    return result


def _timeout(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise argparse.ArgumentTypeError("Timeout must be greater than 0 and at most 300 seconds.")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one preauthorized HeetKit bot without desktop components.")
    parser.add_argument("--data-dir", type=Path, help="Private profile directory (or HEETKIT_DATA_DIR).")
    parser.add_argument("--health-file", type=Path, help="Private ephemeral heartbeat file for container health checks.")
    parser.add_argument("--startup-timeout", type=_timeout, default=60.0, help="Startup deadline in seconds (default 60).")
    parser.add_argument("--shutdown-timeout", type=_timeout, default=20.0, help="Graceful shutdown deadline in seconds (default 20, plus bounded cancellation grace).")
    parser.add_argument("--management-api", action="store_true", help="Enable the private single-administrator API; requires a private management token.")
    parser.add_argument("--management-host", default="127.0.0.1", help="Management bind IP (default loopback).")
    parser.add_argument("--management-port", type=int, default=8765, help="Management port (default 8765).")
    parser.add_argument("--management-allowed-host", help="Exact trusted IP:port Host, required for an all-interface bind.")
    parser.add_argument("--management-trusted-origin", help="Exact external HTTPS DNS origin for explicitly trusted proxy access.")
    parser.add_argument("--management-trusted-proxy", action="append", default=[], help="Exact proxy socket IP; repeat for each trusted proxy. No CIDRs.")
    parser.add_argument("--twitch-redirect-uri", help="External Twitch callback: trusted HTTPS origin followed by /oauth/callback.")
    arguments = parser.parse_args(argv)
    if arguments.data_dir is not None:
        os.environ[DATA_DIR_ENV] = str(arguments.data_dir.expanduser().resolve())
    configure_headless_logging()
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()
    previous_signals = {}
    guards = ExitStack()
    async_failed = False
    previous_umask = os.umask(0o077) if os.name == "posix" else None
    health = HealthFile(arguments.health_file)
    try:
        management_options = {}
        if arguments.management_api:
            from app.management_api import ManagementConfig, load_management_token
            try:
                config = ManagementConfig(load_management_token(), arguments.management_host,
                    arguments.management_port, arguments.management_allowed_host,
                    arguments.management_trusted_origin, tuple(arguments.management_trusted_proxy), arguments.twitch_redirect_uri)
            except ValueError:
                raise HeadlessError("Invalid management configuration. Check the private token, bind IP/port, exact allowed Host or trusted HTTPS origin and proxy IPs. A remote Twitch redirect must equal the trusted origin followed by /oauth/callback.") from None
            management_options["management_config"] = config
        health.update("starting")
        asyncio.set_event_loop(loop)
        def async_failure(_loop, _context) -> None:
            nonlocal async_failed
            async_failed = True
            logger.error("Unhandled backend operation failed; stopping headless.")
            stop.set()
        loop.set_exception_handler(async_failure)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_signals[signum] = signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop.set))
        paths = RuntimePaths.default()
        # Use the identical desktop identity before migrations or stores load.
        guards.enter_context(desktop_instance_guard(paths.app_settings))
        if sys.platform == "win32" and not paths.brand_migration_marker.exists():
            guards.enter_context(desktop_instance_guard(paths.app_settings, legacy_identity=True))
        if paths.is_default_profile and not paths.brand_migration_marker.exists() and paths.former_default_root.is_dir():
            guards.enter_context(desktop_instance_guard(paths.former_default_root / "config" / "app_settings.json", legacy_identity=True))
        # Headless credentials use private environment/file inputs: never discover
        # or prompt an OS keyring, and never accept secrets on the command line.
        settings = Settings(twitch_token_file=str(paths.tokens), database_url="sqlite+aiosqlite:///" + str(paths.database), **secret_file_settings())
        token_file, database_url = prepare_runtime_data(settings.twitch_token_file, settings.database_url)
        settings = settings.model_copy(update={"twitch_token_file": token_file, "database_url": database_url})
        from app.server_setup import credential_manager
        credentials = credential_manager(settings)
        from pydantic import SecretStr
        for name, value in credentials.settings_overrides().items():
            setattr(settings, name, SecretStr(value) if value else None)
        profile = AppSettingsStore(paths.app_settings).snapshot()
        settings = apply_ai_app_settings(apply_twitch_app_settings(settings, profile), profile)
        # Management must remain usable with Twitch stopped/unconfigured. Without
        # it, retain fail-fast diagnostics for the backwards-compatible default.
        if not arguments.management_api and profile.startup.operation_mode == "always_on":
            settings.validate_twitch_configuration()
            if not paths.tokens.is_file():
                raise HeadlessError(AUTHORIZATION_HELP)
        result = loop.run_until_complete(run_headless(settings, profile, stop, startup_timeout=arguments.startup_timeout, shutdown_timeout=arguments.shutdown_timeout, health=health, credentials=credentials, **management_options))
        return 1 if async_failed else result
    except DesktopAlreadyRunningError:
        logger.error("Another HeetKit process owns this profile. Stop it before starting headless.")
        return 1
    except TwitchConfigurationError as error:
        logger.error("%s", error)
        return 1
    except HeadlessError as error:
        logger.error("%s", error)
        return 1
    except Exception as error:
        logger.error("Headless startup failed (%s). Check settings and private profile permissions.", type(error).__name__)
        return 1
    finally:
        try:
            health.clear()
        except OSError:
            logger.error("Could not remove the private health file.")
        for signum, previous in previous_signals.items():
            signal.signal(signum, previous)
        # asyncio.run waits indefinitely for cancellation-resistant tasks. This
        # foreground runner instead gives leftovers a finite cancellation grace.
        pending = asyncio.all_tasks(loop)
        if pending:
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.wait(pending, timeout=1.0))
        loop.close()
        guards.close()
        asyncio.set_event_loop(None)
        if previous_umask is not None:
            os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
