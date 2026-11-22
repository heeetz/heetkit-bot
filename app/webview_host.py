"""pywebview desktop host for the React presentation layer."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from inspect import isawaitable
from urllib.parse import urlsplit
from concurrent.futures import CancelledError as FutureCancelledError, Future, TimeoutError as FutureTimeoutError
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any, Coroutine

from pydantic import SecretStr, ValidationError

from app.app_settings import DEFAULT_INTERFACE_LANGUAGE, AppSettings, AppSettingsStore, TwitchSettings
from app.bot_runtime import BotRuntime
from app.management import APPLICATION_NAME, APPLICATION_SUBTITLE, EXTERNAL_LINKS, ApplicationManagement
from app.command_settings import CommandSettings
from app.commands.registry import command_unavailable_reason
from app.custom_commands import VARIABLES
from app.ai_user_blocks import normalize_ai_username, verified_user_id
from app.config.ai_language import (
    RESPONSE_LANGUAGES, build_response_language_instruction,
)
from app.config.personalities import AI_PERSONALITY_PROMPTS, build_protected_shared_instructions
from app.config.profile_settings import apply_ai_app_settings, apply_twitch_app_settings
from app.config.settings import Settings, TwitchConfigurationError, load_settings_with_credentials
from app.container import Application, build_application
from app.database.migrations import DatabaseMigrationError
from app.credentials import CredentialError, CredentialManager, CredentialName
from app.desktop_instance import (
    DesktopAlreadyRunningError,
    desktop_instance_guard,
    notify_existing_desktop,
)
from app import desktop_relaunch
from app.filter_settings import (
    FilterValidationError,
    apply_filter_settings,
    evaluate_filter_settings,
    get_filter_settings,
    save_filter_settings,
    validate_filter_input,
)
from app.runtime_paths import (
    DATA_DIR_ENV, PACKAGED_FRONTEND, SOURCE_ROOT,
    RuntimePaths, RuntimeDataError, prepare_runtime_data,
)
from app.system_tray import SystemTray
from app.ui_messages import annotate_error
from app.operations import DESKTOP, collect, operation
from app.services.updates import (
    DOWNLOAD_TIMEOUT_SECONDS, ReleaseAssets, UpdateCheckError, VerifiedUpdate,
    authorize_installer, check_for_updates, download_installer, publisher_key,
)
from app.windows_runtime import DesktopPrerequisiteError, ensure_windows_runtime
from app.twitch.client import OAUTH_REDIRECT_URI, TwitchCleanupError, has_saved_bot_authorization
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.utils.logging import (
    RecentLogBuffer,
    configure_logging,
    get_logger,
    get_recent_log_buffer,
)
from app.version import VERSION


FRONTEND_ENTRYPOINT = SOURCE_ROOT / "frontend" / "dist" / "index.html" if SOURCE_ROOT is not None else PACKAGED_FRONTEND
ICON_ROOT = Path(__file__).resolve().parent / "resources"
WINDOWS_APP_ID = "HeetKit.Desktop"
FALLBACK_SHUTDOWN_TIMEOUT_SECONDS = 5.0
FORCED_STOP_TIMEOUT_SECONDS = 2.0
BRIDGE_SETTINGS_TIMEOUT_SECONDS = 10.0
BRIDGE_CREDENTIAL_TEST_TIMEOUT_SECONDS = 15.0
BRIDGE_MODEL_DISCOVERY_TIMEOUT_SECONDS = 20.0
BRIDGE_UPDATE_CHECK_TIMEOUT_SECONDS = 15.0
BRIDGE_BOT_START_TIMEOUT_SECONDS = 10.0
BRIDGE_BOT_STOP_TIMEOUT_SECONDS = 20.0
BRIDGE_TWITCH_RECONNECT_TIMEOUT_SECONDS = 30.0
TRAY_REFRESH_INTERVAL_SECONDS = 2.0

def application_version() -> str:
    return VERSION


class BridgeOperationTimedOut(RuntimeError):
    """A bounded frontend bridge wait expired."""


class AsyncioBackendHost:
    """Own the application and its single asyncio loop on a background thread."""

    def __init__(
        self,
        settings: Settings,
        *,
        auto_start: bool = False,
        initial_ai_memory_enabled: bool | None = None,
    ) -> None:
        self._settings = settings
        self._auto_start = auto_start
        self.run_intent = auto_start
        self._initial_ai_memory_enabled = initial_ai_memory_enabled
        self._logger = get_logger("app.webview")
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._application: Application | None = None
        self._bot_runtime: BotRuntime | None = None
        self._close_lock = threading.Lock()
        self._shutdown_future: Future[Any] | None = None
    @property
    def application(self) -> Application:
        if self._application is None:
            raise RuntimeError("Desktop backend is not ready.")
        return self._application

    @property
    def bot_runtime(self) -> BotRuntime:
        if self._bot_runtime is None:
            raise RuntimeError("Desktop backend is not ready.")
        return self._bot_runtime

    def start(self, timeout: float = 20.0) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="heetkit-asyncio",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("Desktop backend startup timed out.")
        if self._startup_error is not None:
            if isinstance(self._startup_error, DatabaseMigrationError):
                raise self._startup_error from None
            raise RuntimeError("Desktop backend startup failed.") from self._startup_error

    async def _complete_startup(self) -> None:
        await self.bot_runtime.startup()
        if self._auto_start:
            try:
                await self.bot_runtime.start_bot()
            except TwitchConfigurationError as error:
                self.run_intent = False
                self._logger.warning("Automatic Twitch start skipped: %s", error)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            application = build_application(self._settings)
            if self._initial_ai_memory_enabled is not None:
                application.services.runtime_state.set_ai_memory_enabled(
                    self._initial_ai_memory_enabled
                )
            bot_runtime = BotRuntime(application, get_logger("app.twitch"))
            self._application = application
            self._bot_runtime = bot_runtime
            loop.run_until_complete(self._complete_startup())
            self._ready.set()
            loop.run_forever()
        except Exception as error:
            self._startup_error = error
            if isinstance(error, DatabaseMigrationError):
                self._logger.error("Desktop database startup failed: %s", error.operator_message)
            else:
                self._logger.exception("Desktop backend failed")
        finally:
            try:
                if self._bot_runtime is not None and self._shutdown_future is None:
                    self._run_fallback_shutdown(loop)
            finally:
                self._cancel_pending_tasks(loop)
                loop.close()
                self._loop = None
                self._ready.set()

    def _run_fallback_shutdown(self, loop: asyncio.AbstractEventLoop) -> None:
        """Clean up when the loop exits without an externally requested shutdown."""
        if self._bot_runtime is None:
            return
        task = loop.create_task(
            self.bot_runtime.shutdown(),
            name="desktop-backend-shutdown",
        )
        loop.run_until_complete(
            asyncio.wait({task}, timeout=FALLBACK_SHUTDOWN_TIMEOUT_SECONDS)
        )
        if not task.done():
            self._logger.error(
                "Orderly desktop backend cleanup exceeded %.1f seconds; "
                "cancelling pending work",
                FALLBACK_SHUTDOWN_TIMEOUT_SECONDS,
            )
            task.cancel()
            return
        try:
            task.result()
        except asyncio.CancelledError:
            self._logger.warning("Desktop backend cleanup was cancelled")
        except Exception:
            self._logger.exception("Desktop backend cleanup failed")

    def _cancel_pending_tasks(self, loop: asyncio.AbstractEventLoop) -> None:
        """Give cancelled loop tasks a bounded opportunity to release resources."""
        pending = {task for task in asyncio.all_tasks(loop) if not task.done()}
        for _ in range(2):
            if not pending:
                return
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.sleep(0))
            pending = {task for task in asyncio.all_tasks(loop) if not task.done()}
        if pending:
            self._logger.error(
                "%d desktop backend task(s) did not finish cancellation before loop close",
                len(pending),
            )

    @staticmethod
    def _request_forced_loop_stop(loop: asyncio.AbstractEventLoop) -> None:
        def cancel_and_stop() -> None:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.stop()

        try:
            loop.call_soon_threadsafe(cancel_and_stop)
        except RuntimeError:
            pass

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        loop = self._loop
        if loop is None or not loop.is_running():
            coroutine.close()
            raise RuntimeError("Desktop backend is not running.")
        return asyncio.run_coroutine_threadsafe(coroutine, loop)

    def close(
        self,
        timeout: float = 20.0,
        force_timeout: float = FORCED_STOP_TIMEOUT_SECONDS,
    ) -> None:
        with self._close_lock:
            thread = self._thread
            loop = self._loop
            if thread is None:
                return
            if not thread.is_alive():
                self._thread = None
                return

            graceful_timed_out = False
            shutdown_error: Exception | None = None
            if (
                loop is not None
                and loop.is_running()
                and self._bot_runtime is not None
            ):
                if self._shutdown_future is None:
                    self._shutdown_future = self.submit(self.bot_runtime.shutdown())
                try:
                    self._shutdown_future.result(timeout=timeout)
                except FutureTimeoutError:
                    graceful_timed_out = True
                    self._logger.error(
                        "Graceful desktop backend shutdown exceeded %.1f seconds; "
                        "cancelling pending asyncio work",
                        timeout,
                    )
                    self._shutdown_future.cancel()
                except Exception as error:
                    shutdown_error = error

            if loop is not None and loop.is_running():
                if graceful_timed_out:
                    self._request_forced_loop_stop(loop)
                else:
                    loop.call_soon_threadsafe(loop.stop)

            thread.join(timeout=force_timeout)
            if thread.is_alive() and not graceful_timed_out:
                graceful_timed_out = True
                self._logger.error(
                    "Desktop backend thread did not stop after orderly cleanup; "
                    "forcing cancellation"
                )
                if loop is not None:
                    self._request_forced_loop_stop(loop)
                thread.join(timeout=force_timeout)

            thread_alive = thread.is_alive()
            if not thread_alive:
                self._thread = None

            if graceful_timed_out:
                if thread_alive:
                    self._logger.critical(
                        "Desktop backend thread remained alive after forced shutdown; "
                        "the daemon thread will not block process exit"
                    )
                else:
                    self._logger.warning(
                        "Desktop backend stopped through the degraded shutdown path"
                    )
                raise TimeoutError(
                    "Desktop backend graceful shutdown timed out; forced cleanup was requested."
                )
            if shutdown_error is not None:
                raise shutdown_error


class DesktopOperations(ApplicationManagement):
    """Small application-level API exposed to the frontend."""

    def __init__(
        self,
        backend: AsyncioBackendHost,
        log_buffer: RecentLogBuffer | None = None,
        app_settings: AppSettingsStore | None = None,
        credential_manager: CredentialManager | None = None,
    ) -> None:
        self._backend = backend
        self._logger = get_logger("app.webview.bridge")
        self._log_buffer = log_buffer or get_recent_log_buffer()
        self._app_settings = app_settings
        self._credential_manager = credential_manager
        self._twitch_secret_requires_restart = False
        self._profile_root = RuntimePaths.default().root.resolve()
        self._window: Any | None = None
        self._relaunch_ready: Path | None = None
        self._controller: DesktopController | None = None
        self._update_available = False
        self._desktop_operation = threading.Lock()
        self._update_offer: VerifiedUpdate | None = None
        self._prepared_update: Path | None = None
        self._update_progress: dict[str, object] = {}

    @operation(write=False, hosts=(DESKTOP,))
    def get_desktop_startup(self) -> dict[str, object]:
        if self._relaunch_ready is not None:
            try:
                desktop_relaunch.report_desktop_ready(self._relaunch_ready)
                self._relaunch_ready = None
            except OSError:
                self._logger.warning("Could not report Desktop relaunch readiness")
        return {"state": "ready", "windows": sys.platform == "win32"}

    def _wait_for_backend(
        self,
        coroutine: Coroutine[Any, Any, Any],
        *,
        operation: str,
        timeout: float,
    ) -> Any:
        """Wait for one explicit backend operation and cancel it at the UI deadline."""
        try:
            future = self._backend.submit(coroutine)
        except Exception:
            coroutine.close()
            raise
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as error:
            # A coroutine may itself raise TimeoutError. Only treat an unfinished
            # future as the bridge wait reaching its own deadline.
            if future.done():
                raise
            future.add_done_callback(
                lambda completed: self._observe_late_backend_result(
                    operation,
                    completed,
                )
            )
            cancellation_requested = future.cancel()
            self._logger.error(
                "Desktop bridge operation timed out operation=%s "
                "timeout_seconds=%.1f cancellation_requested=%s",
                operation,
                timeout,
                cancellation_requested,
            )
            raise BridgeOperationTimedOut(operation) from error

    @operation(write=True, hosts=(DESKTOP,), failure="Configuration transfer failed. Inspect current settings and private backups before retrying.")
    def export_configuration(self) -> dict[str, object]:
        # pywebview deliberately disables browser downloads. Use a native Save
        # dialog for this explicit action instead of enabling arbitrary downloads.
        import base64
        import webview
        from app.configuration_transfer import ConfigurationTransfer

        result = self._wait_for_backend(
            ApplicationManagement.export_configuration(self), operation="configuration transfer",
            timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
        )
        if not result.get("ok"):
            return result
        if self._window is None:
            return {"ok": False, "error": "The desktop Save dialog is unavailable."}
        temporary = None
        try:
            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE, save_filename=result["filename"],
                file_types=("Configuration ZIP (*.zip)",),
            )
            if not selected:
                return {"ok": True, "cancelled": True}
            path = Path(selected[0])
            if not path.is_absolute() or path.suffix.lower() != ".zip":
                return {"ok": False, "error": "Select a filename ending in .zip in the Save dialog."}
            temporary = ConfigurationTransfer.stage(path, base64.b64decode(result["archive_base64"], validate=True))
            os.replace(temporary, path)
            return {"ok": True, "saved": True}
        except Exception:
            return {"ok": False, "error": "Could not save the configuration ZIP. Check the selected destination and try again."}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _observe_late_backend_result(
        self,
        operation: str,
        future: Future[Any],
    ) -> None:
        """Consume an uncancelled late result so failures never become unobserved."""
        if future.cancelled():
            return
        try:
            future.result()
        except Exception as error:
            self._logger.error(
                "Desktop bridge operation failed after its UI deadline operation=%s",
                operation,
                exc_info=(type(error), error, error.__traceback__),
            )
        else:
            self._logger.warning(
                "Desktop bridge operation completed after its UI deadline operation=%s",
                operation,
            )


    @operation(write=True, hosts=(DESKTOP,))
    def block_ai_user(self, username: object) -> dict[str, object]:
        try:
            self._wait_for_backend(
                self._block_ai_user(username),
                operation="block_ai_user",
                timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "error": "Blocking the AI user timed out. Check Logs and reopen the AI page before trying again.",
            }
        except FutureCancelledError:
            return {"ok": False, "error": "Blocking the AI user was cancelled. Reopen the AI page and try again."}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI user block")
            return {"ok": False, "error": "Could not save AI user block. Check the profile file and try again."}
        return self.get_blocked_ai_users()

    @operation(write=False, hosts=(DESKTOP,))
    def get_profile_info(self) -> dict[str, str]:
        return {"path": str(self._profile_root)}

    @operation(write=False, hosts=(DESKTOP,))
    def check_for_updates(self) -> dict[str, object]:
        if not self._desktop_operation.acquire(blocking=False):
            return {"ok": False, "current_version": application_version(), "error": "A Desktop update is already in progress."}
        try:
            return self._check_for_updates()
        finally:
            self._desktop_operation.release()

    def _check_for_updates(self) -> dict[str, object]:
        self._discard_prepared_update()
        self._update_offer = None
        current_version = application_version()
        try:
            release = self._wait_for_backend(
                check_for_updates(self._backend.application.http_client, current_version),
                operation="check_for_updates",
                timeout=BRIDGE_UPDATE_CHECK_TIMEOUT_SECONDS,
            )
        except BridgeOperationTimedOut:
            return {"ok": False, "current_version": current_version, "error": "The update check timed out. Try again."}
        except UpdateCheckError as error:
            return {"ok": False, "current_version": current_version, "error": str(error)}
        except Exception as error:
            self._logger.warning("Update check failed error_type=%s", type(error).__name__)
            return {"ok": False, "current_version": current_version, "error": "Could not check for updates. Try again later."}
        assets = release.pop("_installer", None)
        result = {"ok": True, "current_version": current_version, **release}
        self._update_available = bool(release.get("update_available"))
        if (refresh := getattr(self._controller, "refresh_tray", None)) is not None:
            refresh()
        if self._controller is None or not release["update_available"]:
            return result
        if desktop_relaunch.installed_directory() is None:
            result["automatic_update_reason"] = "Use Open release / downloads to update this portable or source copy."
        elif (key := publisher_key()) is None:
            result["automatic_update_reason"] = "This build has no trusted update publisher key. Install the update manually."
        elif not isinstance(assets, ReleaseAssets):
            result["automatic_update_reason"] = "This release has no matching installer with publisher verification. Install it manually."
        else:
            try:
                self._update_offer = self._wait_for_backend(
                    authorize_installer(self._backend.application.http_client, assets, key),
                    operation="verify_update_publisher", timeout=BRIDGE_UPDATE_CHECK_TIMEOUT_SECONDS,
                )
            except UpdateCheckError as error:
                result["automatic_update_reason"] = str(error)
            except (OSError, RuntimeError):
                result["automatic_update_reason"] = "Publisher verification is unavailable. Install the update manually."
        result["automatic_update"] = self._update_offer is not None
        return result

    def _discard_prepared_update(self) -> None:
        if self._prepared_update is not None:
            shutil.rmtree(self._prepared_update, ignore_errors=True)
            self._prepared_update = None
        self._update_progress = {}

    @operation(write=False, hosts=(DESKTOP,))
    def get_desktop_update_progress(self) -> dict[str, object]:
        return self._update_progress

    @operation(write=True, hosts=(DESKTOP,))
    def prepare_desktop_update(self, version: object) -> dict[str, object]:
        if not self._desktop_operation.acquire(blocking=False):
            return {"ok": False, "error": "A Desktop update or restart is already in progress."}
        stage = None
        try:
            update = self._update_offer
            install = desktop_relaunch.installed_directory()
            if update is None or version != update.assets.version or install is None or self._controller is None:
                return {"ok": False, "error": "Check for a verified update first."}
            if self._prepared_update is not None:
                return {"ok": True}
            stage = desktop_relaunch.new_work_directory(self._profile_root, install)

            def progress(phase: str, size: int) -> None:
                self._update_progress = {"phase": phase, "downloaded": size, "total": update.assets.size}

            self._wait_for_backend(
                download_installer(self._backend.application.http_client, update, stage / update.assets.name, progress),
                operation="download_installer", timeout=DOWNLOAD_TIMEOUT_SECONDS + 30,
            )
            desktop_relaunch.verify_installer_version(stage / update.assets.name, update.assets.version)
            desktop_relaunch.prepare_worker_copy(stage, install)
            self._prepared_update = stage
            progress("ready", update.assets.size)
            return {"ok": True}
        except UpdateCheckError as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError) as error:
            self._logger.warning("Update preparation failed error_type=%s", type(error).__name__)
            return {"ok": False, "error": "Could not prepare the update. Check free disk space and try again."}
        finally:
            if stage is not None and self._prepared_update != stage:
                shutil.rmtree(stage, ignore_errors=True)
                self._update_progress = {}
            self._desktop_operation.release()

    @operation(write=True, hosts=(DESKTOP,))
    def finish_desktop_update(self, version: object) -> dict[str, object]:
        return self._schedule_desktop_relaunch(version, update_requested=True)

    @operation(write=True, hosts=(DESKTOP,))
    def restart_desktop(self) -> dict[str, object]:
        return self._schedule_desktop_relaunch()

    def _schedule_desktop_relaunch(self, version: object = None, *, update_requested: bool = False) -> dict[str, object]:
        if self._controller is None or not self._desktop_operation.acquire(blocking=False):
            return {"ok": False, "error": "Desktop restart is unavailable or another operation is in progress."}
        stage = None
        try:
            if update_requested:
                stage, update = self._prepared_update, self._update_offer
                install = desktop_relaunch.installed_directory()
                if stage is None or update is None or install is None or version != update.assets.version:
                    return {"ok": False, "error": "Prepare a verified update first."}
            else:
                update = install = None
                pending = self._app_settings is not None and self._twitch_setup_requires_restart(self._app_settings.snapshot().twitch)
                if not pending and not self._twitch_cleanup_requires_restart():
                    return {"ok": False, "error": "There are no Twitch changes requiring a Desktop restart."}
                stage = desktop_relaunch.new_work_directory(self._profile_root)
            self._controller.schedule_relaunch(stage, install=install, update=update)
            if update_requested:
                self._prepared_update = None
                self._update_offer = None
            return {"ok": True}
        except (OSError, RuntimeError) as error:
            self._logger.warning("Desktop restart preparation failed error_type=%s", type(error).__name__)
            if update_requested:
                self._discard_prepared_update()
            elif stage is not None:
                shutil.rmtree(stage, ignore_errors=True)
            return {"ok": False, "error": "Could not start the Desktop relaunch. HeetKit is still running. Try again or use Exit from the tray."}
        finally:
            self._desktop_operation.release()

    @operation(write=True, hosts=(DESKTOP,))
    def open_profile_folder(self) -> dict[str, object]:
        """Open only this desktop's selected profile, never a frontend-supplied path."""
        try:
            if not self._profile_root.is_dir():
                return {"ok": False, "error": "The profile folder is no longer available."}
            if sys.platform == "win32":
                os.startfile(str(self._profile_root), "explore")
            else:
                subprocess.run(
                    ["open" if sys.platform == "darwin" else "xdg-open", str(self._profile_root)],
                    check=True,
                    timeout=5,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except (OSError, subprocess.SubprocessError):
            self._logger.warning("Could not open the profile folder")
            return {"ok": False, "error": "Could not open the profile folder in the system file manager."}
        return {"ok": True}

    @operation(write=True, hosts=(DESKTOP,))
    def open_external_link(self, destination: object) -> dict[str, object]:
        if not isinstance(destination, str) or destination not in (*EXTERNAL_LINKS, "twitch_authorization"):
            return {"ok": False, "error": "That external link is not available."}
        url = EXTERNAL_LINKS.get(destination, "")
        if destination == "twitch_authorization":
            application = self._backend.application
            runtime_state = application.services.runtime_state
            if not runtime_state.status()[0]:
                return {"ok": False, "error": "Start Bot before authorizing Twitch."}
            if runtime_state.twitch_connection_state not in ("auth_required", "connected"):
                return {"ok": False, "error": "Twitch authorization is not currently required."}
            try:
                application.settings.validate_twitch_configuration()
            except TwitchConfigurationError as error:
                return {"ok": False, "error": str(error)}
            if self._app_settings is not None and self._twitch_setup_requires_restart(
                self._app_settings.snapshot().twitch
            ):
                return {"ok": False, "error": "Restart the application to apply the saved Twitch client ID, bot identity or secret."}
            try:
                if application.services.twitch is None:
                    return {"ok": False, "error": "Twitch authorization is not ready."}
                url = self._wait_for_backend(
                    application.services.twitch.begin_authorization(),
                    operation="begin_twitch_authorization",
                    timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
                )
            except ValueError as error:
                return {"ok": False, "error": str(error)}
            except BridgeOperationTimedOut:
                return {"ok": False, "error": "Twitch authorization timed out. Try again."}
            except Exception as error:
                self._logger.warning("Could not begin Twitch authorization error_type=%s", type(error).__name__)
                return {"ok": False, "error": "Could not begin Twitch authorization."}
        try:
            opened = webbrowser.open(url, new=2)
        except Exception:
            self._logger.exception("Could not open external link destination=%s", destination)
            return {"ok": False, "error": "Could not open the external link."}
        if not opened:
            return {"ok": False, "error": "Could not open the external link."}
        self._logger.info("Opened external link destination=%s", destination)
        return {"ok": True}


    def _filter_action(self, payload: object, *, save: bool) -> dict[str, object]:
        action = "save" if save else "apply"
        try:
            self._wait_for_backend(
                self._change_filters(payload, save=save),
                operation=f"{action} filters",
                timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
            )
        except FilterValidationError as error:
            return {
                "ok": False,
                "error": str(error),
                "invalid_rule": {"category": error.category, "index": error.index},
            }
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except (OSError, BridgeOperationTimedOut):
            self._logger.exception("Could not %s filters", action)
            return {"ok": False, "error": f"Could not {action} filters."}
        self._logger.info("Global filters %s", "saved" if save else "applied")
        return {"ok": True}

    @operation(write=True, hosts=(DESKTOP,))
    def apply_filters(self, payload: object) -> dict[str, object]:
        return self._filter_action(payload, save=False)

    @operation(write=True, hosts=(DESKTOP,))
    def save_filters(self, payload: object) -> dict[str, object]:
        return self._filter_action(payload, save=True)


    @operation(write=True, hosts=(DESKTOP,))
    def test_filters(
        self, text: object, source: object, payload: object = None
    ) -> dict[str, object]:
        try:
            return self._wait_for_backend(
                self._test_filters(text, source, payload),
                operation="test filters",
                timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
            )
        except FilterValidationError as error:
            return {
                "ok": False,
                "error": str(error),
                "invalid_rule": {"category": error.category, "index": error.index},
            }
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {"ok": False, "error": "Filter test timed out. Try again."}


    @operation(write=True, hosts=(DESKTOP,), failure="The Playground is unavailable. Try again.",
               timeout_failure="Playground control timed out. Try again.")
    async def start_ai_playground(self, prompt: object) -> dict[str, object]:
        return self._backend.application.ai_playground.start(prompt)

    @operation(write=True, hosts=(DESKTOP,), failure="The Playground is unavailable. Try again.",
               timeout_failure="Playground control timed out. Try again.")
    async def get_ai_playground_result(self, request_id: object) -> dict[str, object]:
        return self._backend.application.ai_playground.get(request_id)

    @operation(write=True, hosts=(DESKTOP,), failure="The Playground is unavailable. Try again.",
               timeout_failure="Playground control timed out. Try again.")
    async def cancel_ai_playground(self, request_id: object) -> dict[str, object]:
        return self._backend.application.ai_playground.cancel(request_id)

    @operation(write=True, hosts=(DESKTOP,))
    def set_ai_memory_enabled(self, enabled: object) -> dict[str, object]:
        try:
            parsed_enabled = self._validate_toggle(enabled)
            self._wait_for_backend(
                self._save_ai_memory_enabled(parsed_enabled),
                operation="save_ai_memory",
                timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "error": "Saving the AI memory setting timed out. Check Logs for details.",
            }
        except OSError:
            self._logger.exception("Could not save AI memory setting")
            return {"ok": False, "error": "Could not save AI memory setting."}
        except Exception:
            self._logger.exception("Could not save AI memory setting")
            return {"ok": False, "error": "Could not save AI memory setting."}
        self._logger.info(
            "AI memory setting changed enabled=%s",
            parsed_enabled,
            extra={
                "event_kind": "settings.ai",
                "event_setting": "memory",
                "event_action": "save",
            },
        )
        return {"ok": True}


    @operation(write=False, hosts=(DESKTOP,))
    def get_interface_language(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": True, "language": DEFAULT_INTERFACE_LANGUAGE}
        return {"ok": True, "language": self._app_settings.snapshot().interface.language}

    @operation(write=True, hosts=(DESKTOP,))
    def set_interface_language(self, language: object) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            self._app_settings.update_interface_language(language)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save the interface language")
            return {"ok": False, "error": "Could not save the interface language."}
        if (refresh := getattr(self._controller, "refresh_tray", None)) is not None:
            refresh()
        return {"ok": True}

    @operation(write=False, hosts=(DESKTOP,))
    def get_app_settings(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        settings = self._app_settings.snapshot()
        return {
            "ok": True,
            "settings": {
                "auto_start_bot": settings.startup.auto_start_bot,
                "start_minimized": settings.window.start_minimized,
                "minimize_to_tray": settings.window.minimize_to_tray,
                "close_to_tray": settings.window.close_to_tray,
                "tray_available": sys.platform == "win32",
            },
        }

    @operation(write=True, hosts=(DESKTOP,))
    def update_app_settings(
        self,
        start_minimized: object,
        minimize_to_tray: object,
        close_to_tray: object,
        auto_start_bot: object,
    ) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            self._app_settings.update_desktop(
                start_minimized=start_minimized,
                minimize_to_tray=minimize_to_tray,
                close_to_tray=close_to_tray,
                auto_start_bot=auto_start_bot,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save desktop settings")
            return {"ok": False, "error": "Could not save desktop settings."}
        self._logger.info(
            "Desktop application settings saved",
            extra={
                "event_kind": "settings.desktop",
                "event_action": "save",
            },
        )
        return {"ok": True}

    @operation(write=False, hosts=(DESKTOP,))
    def get_twitch_settings(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        application = self._backend.application
        runtime_state = application.services.runtime_state
        local = self._app_settings.snapshot().twitch
        target_channel = local.channel or application.settings.twitch_channel
        target_channel_user_id = (
            local.channel_user_id or application.settings.twitch_channel_user_id
        )
        matching_active_presets = tuple(
            preset
            for preset in local.presets
            if preset.channel == application.settings.twitch_channel
            and preset.channel_user_id == application.settings.twitch_channel_user_id
        )
        active_preset = next(
            (
                preset
                for preset in matching_active_presets
                if preset.id == local.selected_preset_id
            ),
            matching_active_presets[0] if matching_active_presets else None,
        )
        return {
            "ok": True,
            "settings": {
                "target_channel": target_channel,
                "target_channel_user_id": target_channel_user_id,
                "active_channel": application.settings.twitch_channel,
                "active_channel_user_id": application.settings.twitch_channel_user_id,
                "presets": [
                    {
                        "id": preset.id,
                        "display_name": preset.display_name,
                        "target_channel": preset.channel,
                        "target_channel_user_id": preset.channel_user_id,
                    }
                    for preset in local.presets
                ],
                "selected_preset_id": local.selected_preset_id,
                "active_preset_id": active_preset.id if active_preset else None,
                "requires_reconnect": (
                    target_channel != application.settings.twitch_channel
                    or target_channel_user_id
                    != application.settings.twitch_channel_user_id
                ),
                "client_id": local.client_id or getattr(application.settings, "twitch_client_id", ""),
                "bot_username": local.bot_username or application.settings.twitch_bot_username,
                "bot_user_id": local.bot_user_id or application.settings.twitch_bot_user_id,
                "active_client_id": getattr(application.settings, "twitch_client_id", ""),
                "active_bot_username": application.settings.twitch_bot_username,
                "active_bot_user_id": application.settings.twitch_bot_user_id,
                "requires_secret_restart": self._twitch_secret_requires_restart,
                "requires_cleanup_restart": self._twitch_cleanup_requires_restart(),
                "requires_restart": self._twitch_setup_requires_restart(local),
                "running": runtime_state.status()[0],
                "connected": runtime_state.twitch_connected,
                "oauth_token_available": Path(
                    application.settings.twitch_token_file
                ).is_file(),
                "saved_bot_authorization": has_saved_bot_authorization(application.settings),
                "oauth_callback_url": OAUTH_REDIRECT_URI,
                "has_local_override": (
                    local.channel is not None
                    and local.channel_user_id is not None
                ),
            },
        }

    @operation(write=True, hosts=(DESKTOP,))
    def update_twitch_settings(
        self,
        target_channel: object,
        target_channel_user_id: object,
        selected_preset_id: object = None,
        client_id: object = None,
        bot_username: object = None,
        bot_user_id: object = None,
    ) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            updated = self._app_settings.update_twitch(
                channel=target_channel,
                channel_user_id=target_channel_user_id,
                selected_preset_id=selected_preset_id,
                client_id=client_id,
                bot_username=bot_username,
                bot_user_id=bot_user_id,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save Twitch connection settings")
            return {"ok": False, "error": "Could not save Twitch settings."}
        application_settings = self._backend.application.settings
        requires_reconnect = (
            updated.twitch.channel != application_settings.twitch_channel
            or updated.twitch.channel_user_id
            != application_settings.twitch_channel_user_id
        )
        self._logger.info(
            "Twitch target channel settings saved",
            extra={
                "event_kind": "settings.twitch",
                "event_channel": str(updated.twitch.channel),
                "event_action": "save",
            },
        )
        return {
            "ok": True, "requires_reconnect": requires_reconnect,
            "requires_restart": self._twitch_setup_requires_restart(updated.twitch) or self._twitch_cleanup_requires_restart(),
        }

    def _twitch_setup_requires_restart(self, local: TwitchSettings) -> bool:
        active = self._backend.application.settings
        return self._twitch_secret_requires_restart or any(
            value is not None and value != getattr(active, f"twitch_{name}", "")
            for name, value in (
                ("client_id", local.client_id), ("bot_username", local.bot_username),
                ("bot_user_id", local.bot_user_id),
            )
        )

    def _twitch_cleanup_requires_restart(self) -> bool:
        return getattr(getattr(self._backend, "bot_runtime", None), "twitch_restart_required", False) is True

    @operation(write=True, hosts=(DESKTOP,))
    def save_twitch_preset(
        self,
        preset_id: object,
        display_name: object,
        target_channel: object,
        target_channel_user_id: object,
    ) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            updated, preset = self._app_settings.save_twitch_preset(
                preset_id=preset_id,
                display_name=display_name,
                channel=target_channel,
                channel_user_id=target_channel_user_id,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save Twitch connection preset")
            return {"ok": False, "error": "Could not save Twitch preset."}
        application_settings = self._backend.application.settings
        requires_reconnect = (
            updated.twitch.channel != application_settings.twitch_channel
            or updated.twitch.channel_user_id
            != application_settings.twitch_channel_user_id
        )
        self._logger.info(
            "Twitch connection preset saved",
            extra={
                "event_kind": "settings.twitch_preset",
                "event_channel": preset.channel,
                "event_action": "save",
            },
        )
        return {
            "ok": True,
            "preset_id": preset.id,
            "requires_reconnect": requires_reconnect,
        }

    @operation(write=True, hosts=(DESKTOP,))
    def delete_twitch_preset(self, preset_id: object) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            self._app_settings.delete_twitch_preset(preset_id)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not delete Twitch connection preset")
            return {"ok": False, "error": "Could not delete Twitch preset."}
        self._logger.info(
            "Twitch connection preset deleted",
            extra={
                "event_kind": "settings.twitch_preset",
                "event_action": "delete",
            },
        )
        return {"ok": True}

    @operation(write=True, hosts=(DESKTOP,))
    def reconnect_twitch(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        application = self._backend.application
        local = self._app_settings.snapshot().twitch
        if self._twitch_setup_requires_restart(local):
            return {"ok": False, "error": "Restart the application to apply the saved Twitch client ID, bot identity or secret."}
        channel = local.channel or application.settings.twitch_channel
        channel_user_id = (
            local.channel_user_id or application.settings.twitch_channel_user_id
        )
        try:
            reconnected = self._wait_for_backend(
                self._backend.bot_runtime.reconnect_twitch(
                    channel=channel,
                    channel_user_id=channel_user_id,
                ),
                operation="reconnect_twitch",
                timeout=BRIDGE_TWITCH_RECONNECT_TIMEOUT_SECONDS,
            )
        except (TwitchConfigurationError, TwitchCleanupError) as error:
            return {"ok": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "error": "Twitch reconnect timed out. Check Logs for details.",
            }
        except Exception:
            self._logger.exception("Twitch reconnect failed")
            return {"ok": False, "error": "Could not reconnect Twitch."}
        self._logger.info(
            "Twitch target settings applied reconnected=%s",
            reconnected,
            extra={
                "event_kind": "twitch.reconnect",
                "event_channel": channel,
                "event_action": "reconnect" if reconnected else "apply",
            },
        )
        return {"ok": True, "changed": reconnected}


    @operation(write=True, hosts=(DESKTOP,))
    def update_ai_language_settings(
        self, mode: object, allowed_languages: object, fallback_language: object,
    ) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            self._wait_for_backend(
                self._save_ai_response_language(mode, allowed_languages, fallback_language),
                operation="save_ai_language", timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {"ok": False, "error": "Saving response language settings timed out. Check Logs for details."}
        except Exception:
            self._logger.exception("Could not save AI response language settings")
            return {"ok": False, "error": "Could not save response language settings."}
        self._logger.info(
            "AI response language settings saved",
            extra={"event_kind": "settings.ai", "event_action": "save"},
        )
        return {"ok": True}


    @operation(write=True, hosts=(DESKTOP,))
    def discover_ai_models(self, provider: object = None) -> dict[str, object]:
        from app.config.ai_models import validate_ai_provider
        from app.services.ai_provider import AIModelDiscoveryError
        try:
            selected = validate_ai_provider(provider if provider is not None else self._backend.application.settings.ai_provider)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        service = self._backend.application.services.ai
        discover = getattr(service, "discover_models", None)
        if discover is None:
            return {"ok": False, "error": "AI model discovery is unavailable."}
        try:
            models = self._wait_for_backend(
                discover(selected),
                operation="discover_ai_models",
                timeout=BRIDGE_MODEL_DISCOVERY_TIMEOUT_SECONDS,
            )
        except AIModelDiscoveryError as error:
            return {"ok": False, "error": str(error), "error_code": error.code, "provider_id": selected}
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "error": "AI model discovery timed out. Check Logs for details.",
            }
        except Exception:
            self._logger.warning("AI model discovery failed")
            return {"ok": False, "error": "Could not discover AI models."}
        return {"ok": True, "models": models, "provider_id": selected}

    @operation(write=False, hosts=(DESKTOP,))
    def get_credentials(self) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        return {
            "ok": True,
            "credentials": [
                status.serialize() for status in self._credential_manager.statuses()
            ],
        }

    async def _refresh_ai_credential(self, name: CredentialName) -> None:
        value = self._credential_manager.effective_value(name)
        setattr(self._backend.application.settings, name.value, SecretStr(value) if value else None)

    def _apply_credential_change(self, name: CredentialName, previous: str | None) -> dict[str, object]:
        if name is CredentialName.TWITCH_CLIENT_SECRET:
            active = self._backend.application.settings.twitch_client_secret
            effective = self._credential_manager.effective_value(name)
            self._twitch_secret_requires_restart = effective != (active.get_secret_value() if active else None)
            return {"changed": effective != previous, "requires_restart": self._twitch_secret_requires_restart}
        self._wait_for_backend(
            self._refresh_ai_credential(name), operation="apply_ai_credential",
            timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
        )
        return {}

    @operation(write=True, hosts=(DESKTOP,))
    def replace_credential(self, name: object, value: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            previous = self._credential_manager.effective_value(parsed_name) if parsed_name is CredentialName.TWITCH_CLIENT_SECRET else None
            self._credential_manager.replace(parsed_name.value, value)
            outcome = self._apply_credential_change(parsed_name, previous)
        except BridgeOperationTimedOut:
            return {"ok": False, "error": "Credential stored securely. Its runtime status could not be refreshed. Try saving it again."}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except CredentialError as error:
            self._logger.warning(
                "Credential replacement failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid",
                type(error).__name__,
            )
            return {"ok": False, "error": str(error)}
        self._logger.info(
            "Credential replaced name=%s",
            parsed_name.value,
            extra={
                "event_kind": "settings.credential",
                "event_setting": parsed_name.value,
                "event_action": "replace",
            },
        )
        return {"ok": True, **outcome}

    @operation(write=True, hosts=(DESKTOP,))
    def remove_credential(self, name: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            previous = self._credential_manager.effective_value(parsed_name) if parsed_name is CredentialName.TWITCH_CLIENT_SECRET else None
            removed = self._credential_manager.remove(parsed_name.value)
            outcome = self._apply_credential_change(parsed_name, previous) if removed or parsed_name is not CredentialName.TWITCH_CLIENT_SECRET else {}
        except BridgeOperationTimedOut:
            return {"ok": False, "error": "Credential removed. Its runtime status could not be refreshed. Try removing it again."}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except CredentialError as error:
            self._logger.warning(
                "Credential removal failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid",
                type(error).__name__,
            )
            return {"ok": False, "error": str(error)}
        if removed:
            self._logger.info(
                "Credential removed name=%s",
                parsed_name.value,
                extra={
                    "event_kind": "settings.credential",
                    "event_setting": parsed_name.value,
                    "event_action": "remove",
                },
            )
        return {"ok": True, "changed": removed, **outcome}

    @operation(write=True, hosts=(DESKTOP,))
    def test_credential(self, name: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            application = self._backend.application
            self._wait_for_backend(
                self._credential_manager.test(
                    parsed_name.value,
                    http_client=application.http_client,
                    twitch_client_id=application.settings.twitch_client_id,
                ),
                operation=f"test_credential:{parsed_name.value}",
                timeout=BRIDGE_CREDENTIAL_TEST_TIMEOUT_SECONDS,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "error": "Credential test timed out. Check Logs for details.",
            }
        except CredentialError as error:
            self._logger.warning(
                "Credential test failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid",
                type(error).__name__,
            )
            return {"ok": False, "error": str(error)}
        except Exception:
            self._logger.exception(
                "Credential test failed name=%s",
                name if isinstance(name, str) else "invalid",
            )
            return {"ok": False, "error": "Credential test failed."}
        self._logger.info(
            "Credential test passed name=%s",
            parsed_name.value,
            extra={
                "event_kind": "settings.credential",
                "event_setting": parsed_name.value,
                "event_action": "test",
            },
        )
        return {"ok": True}

    @operation(write=False, hosts=(DESKTOP,))
    def get_recent_logs(self, after_id: int = 0, limit: int = 200, snapshot: bool = False) -> dict[str, object]:
        safe_after_id = after_id if type(after_id) is int and after_id >= 0 else 0
        safe_limit = limit if type(limit) is int else 200
        safe_limit = min(200, max(1, safe_limit))
        return self._log_buffer.activity(after_id=safe_after_id, limit=safe_limit, snapshot=snapshot is True and safe_after_id == 0)

    @operation(write=False, hosts=(DESKTOP,))
    def get_recent_commands(self) -> dict[str, object]:
        return {"ok": True, "entries": self._log_buffer.recent_commands()}

    @operation(write=True, hosts=(DESKTOP,))
    def export_activity(self, entry_ids: object) -> dict[str, object]:
        """Save only retained events selected by the confirmed view, via a native dialog."""
        import json
        import webview
        from datetime import datetime, timezone
        from app.configuration_transfer import ConfigurationTransfer

        if (not isinstance(entry_ids, list) or not 1 <= len(entry_ids) <= 500
                or any(type(value) is not int or value < 1 for value in entry_ids)
                or len(set(entry_ids)) != len(entry_ids)):
            return {"ok": False, "error": "Select up to 500 retained events to export."}
        retained = {entry["id"]: entry for entry in self._log_buffer.activity(limit=500)["entries"]}
        if any(value not in retained for value in entry_ids):
            return {"ok": False, "error": "Some selected events have expired. Clear the view and select recent events."}
        if self._window is None:
            return {"ok": False, "error": "The desktop Save dialog is unavailable."}
        payload = json.dumps({"exported_at": datetime.now(timezone.utc).isoformat(),
                              "entries": [retained[value] for value in entry_ids]}, ensure_ascii=False).encode("utf-8")
        temporary = None
        try:
            selected = self._window.create_file_dialog(webview.FileDialog.SAVE,
                save_filename="heetkit-activity.json", file_types=("Activity JSON (*.json)",))
            if not selected:
                return {"ok": True, "cancelled": True}
            path = Path(selected[0])
            if not path.is_absolute() or path.suffix.lower() != ".json":
                return {"ok": False, "error": "Select a filename ending in .json in the Save dialog."}
            temporary = ConfigurationTransfer.stage(path, payload)
            os.replace(temporary, path)
            return {"ok": True, "saved": True}
        except Exception:
            return {"ok": False, "error": "Could not save activity. Check the selected destination and try again."}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @operation(write=True, hosts=(DESKTOP,))
    def start_bot(self) -> dict[str, object]:
        if self._app_settings is not None and self._twitch_setup_requires_restart(
            self._app_settings.snapshot().twitch
        ):
            return {"ok": False, "changed": False, "error": "Restart the application to apply the saved Twitch client ID, bot identity or secret."}
        try:
            started = self._wait_for_backend(
                self._backend.bot_runtime.start_bot(),
                operation="start_bot",
                timeout=BRIDGE_BOT_START_TIMEOUT_SECONDS,
            )
        except (TwitchConfigurationError, TwitchCleanupError) as error:
            return {"ok": False, "changed": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "changed": False,
                "error": "Starting the bot timed out. Check Logs for details.",
            }
        except Exception:
            self._logger.exception("Desktop UI could not start the bot")
            return {"ok": False, "changed": False, "error": "Could not start the bot."}
        self._logger.info(
            "Desktop bot start requested changed=%s",
            started,
            extra={
                "event_kind": "twitch.start",
                "event_channel": self._backend.application.settings.twitch_channel,
                "event_action": "start",
            },
        )
        self._backend.run_intent = True
        return {"ok": True, "changed": started}

    @operation(write=True, hosts=(DESKTOP,))
    def stop_bot(self) -> dict[str, object]:
        try:
            stopped = self._wait_for_backend(
                self._backend.bot_runtime.stop_bot(),
                operation="stop_bot",
                timeout=BRIDGE_BOT_STOP_TIMEOUT_SECONDS,
            )
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "changed": False,
                "error": "Stopping the bot timed out. Check Logs for details.",
            }
        except Exception:
            self._logger.exception("Desktop UI could not stop the bot")
            return {"ok": False, "changed": False, "error": "Could not stop the bot."}
        self._logger.info(
            "Desktop bot stop requested changed=%s",
            stopped,
            extra={
                "event_kind": "twitch.stop",
                "event_channel": self._backend.application.settings.twitch_channel,
                "event_action": "stop",
            },
        )
        self._backend.run_intent = False
        return {"ok": True, "changed": stopped}


class WebUIBridge(DesktopOperations):
    """Validate and execute the Desktop registry through one pywebview entry point."""

    def call(self, name: str, payload: object) -> dict[str, object]:
        operation = DESKTOP_OPERATIONS.get(name) if isinstance(name, str) else None
        if operation is None:
            return {"ok": False, "error": "Unknown operation."}
        try:
            arguments = operation.bind(payload)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        try:
            method = getattr(self, operation.attribute)
            result = method(**arguments)
            if isawaitable(result):
                result = self._wait_for_backend(result, operation=name, timeout=operation.timeout)
            return result if isinstance(result, dict) else {"ok": True}
        except BridgeOperationTimedOut:
            return {"ok": False, "error": operation.timeout_failure or operation.failure or "Management operation unavailable. Check profile storage and retry."}
        except FutureCancelledError:
            return {"ok": False, "error": operation.cancelled_failure or operation.failure or "Management operation unavailable. Check profile storage and retry."}
        except ValueError as error:
            return {"ok": False, "error": operation.validation_failure or str(error)}
        except Exception:
            self._logger.exception("Desktop operation failed operation=%s", name)
            return {"ok": False, "error": operation.failure or "Management operation unavailable. Check profile storage and retry."}


DESKTOP_OPERATIONS = {name: op for name, op in collect(ApplicationManagement, DesktopOperations).items()
                      if DESKTOP in op.hosts}


def resolve_frontend_url(dev_url: str | None) -> str:
    if dev_url:
        if getattr(sys, "frozen", False) or SOURCE_ROOT is None:
            raise ValueError("--dev-url is available only in a source checkout.")
        origin = _frontend_origin(dev_url)
        parsed = urlsplit(dev_url)
        if origin is None or origin[1] not in {"localhost", "127.0.0.1", "::1"} or parsed.username is not None or parsed.password is not None:
            raise ValueError("--dev-url must be an HTTP(S) loopback development server URL.")
        return dev_url
    if PACKAGED_FRONTEND.is_file():
        return str(PACKAGED_FRONTEND)
    if not FRONTEND_ENTRYPOINT.is_file():
        raise FileNotFoundError(
            "Frontend build is missing. Source launches require 'npm install' and 'npm run build' in frontend/. "
            "Installed distributions require prebuilt assets in app/resources/frontend/."
        )
    return str(FRONTEND_ENTRYPOINT)


def _frontend_origin(url: str | None) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def expose_frontend_operations(window: Any, bridge: WebUIBridge) -> None:
    """Expose only named operations, bound to the initial frontend origin."""
    trusted_origin: tuple[str, str, int] | None = None

    def pin_origin(renderer: str) -> None:
        nonlocal trusted_origin
        # pywebview resolves the bundled file to its loopback server at initialize.
        trusted_origin = _frontend_origin(window.real_url)

    window.events.initialized += pin_origin

    def call(name: str, payload: object) -> Any:
        if trusted_origin is None or _frontend_origin(window.get_current_url()) != trusted_origin:
            return {"ok": False, "error": "This page cannot access the application bridge."}
        return annotate_error(bridge.call(name, payload))

    window.expose(call)


def resolve_auto_start(app_settings: AppSettings, override: bool | None) -> bool:
    if override is not None:
        return override
    return app_settings.startup.auto_start_bot


class DesktopController:
    """Coordinate one pywebview window, tray icon, and backend lifecycle."""

    def __init__(
        self,
        backend: AsyncioBackendHost,
        bridge: WebUIBridge,
        app_settings: AppSettingsStore,
        tray: SystemTray | None = None,
        dev_url: str | None = None,
    ) -> None:
        self._backend = backend
        self._bridge = bridge
        self._app_settings = app_settings
        self._logger = get_logger("app.webview.desktop")
        self._window: Any | None = None
        self._exit_requested = False
        self._tray_started = False
        self._tray_supported = sys.platform == "win32" or tray is not None
        self._exit_lock = threading.RLock()
        self._dev_url = dev_url
        self._relaunch_stage: Path | None = None
        self._tray = tray or SystemTray(
            on_open=self.open_window,
            on_toggle_bot=self.toggle_bot,
            on_exit=self.exit_application,
            is_bot_running=self.is_bot_running,
            language=self.interface_language,
            status=self.tray_status,
            update_available=self.update_available,
            on_open_update=self.open_update,
        )
        self._tray_refresh_stop = threading.Event()
        self._tray_refresh_thread: threading.Thread | None = None
        self._tray_signature: tuple[object, ...] | None = None

    def bind_window(self, window: Any) -> None:
        self._window = window
        window.events.closing += self._on_closing
        window.events.closed += self._on_closed
        window.events.minimized += self._on_minimized

    def start_tray(self) -> None:
        with self._exit_lock:
            if not self._tray_supported or self._tray_started or self._exit_requested:
                return
            try:
                self._tray.start()
            except Exception:
                self._logger.exception("System tray is unavailable; keeping the window visible")
                if self._window is not None:
                    self._window.show()
            else:
                self._tray_started = True
                self._start_tray_refresh()

    def interface_language(self) -> str:
        return self._app_settings.snapshot().interface.language

    def update_available(self) -> bool:
        return bool(getattr(self._bridge, "_update_available", False))

    def tray_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        running, _ = runtime_state.status()
        return {
            "running": running,
            "twitch_connection_state": runtime_state.twitch_connection_state,
            "channel": application.settings.twitch_channel,
        }

    def _tray_state(self) -> tuple[object, ...]:
        status = self.tray_status()
        return (self.interface_language(), status.get("running"), status.get("twitch_connection_state"),
                status.get("channel"), self.update_available())

    def refresh_tray(self) -> None:
        """Rebuild the tray menu when its language, status or update item changed."""
        if not self._tray_started:
            return
        try:
            signature = self._tray_state()
        except Exception:
            return
        if signature == self._tray_signature:
            return
        self._tray_signature = signature
        try:
            self._tray.update_menu()
        except Exception:
            self._logger.exception("Could not refresh the tray menu")

    def _start_tray_refresh(self) -> None:
        if self._tray_refresh_thread is not None:
            return

        def run() -> None:
            # pystray builds the Windows menu on update_menu(), so poll the cheap
            # status signature and rebuild only on change.
            while not self._tray_refresh_stop.wait(TRAY_REFRESH_INTERVAL_SECONDS):
                self.refresh_tray()

        try:
            # The menu was just built from the current state.
            self._tray_signature = self._tray_state()
        except Exception:
            self._tray_signature = None
        self._tray_refresh_thread = threading.Thread(target=run, name="heetkit-tray-refresh", daemon=True)
        self._tray_refresh_thread.start()

    def open_update(self) -> None:
        """Show the window on About, where the update can be installed."""
        self.open_window()
        window = self._window
        if window is None:
            return
        try:
            window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('heetkit:navigate',"
                " {detail: {section: 'About', target: 'desktop-updates'}}))"
            )
        except Exception:
            self._logger.exception("Could not open About from the tray")

    def is_bot_running(self) -> bool:
        return bool(self._backend.application.services.runtime_state.status()[0])

    def open_window(self) -> None:
        window = self._window
        if window is None:
            return
        try:
            window.show()
            window.restore()
        except Exception:
            self._logger.exception("Could not restore desktop window")

    def toggle_bot(self) -> None:
        result = (
            self._bridge.stop_bot()
            if self.is_bot_running()
            else self._bridge.start_bot()
        )
        if not result.get("ok"):
            self._logger.error("Tray could not change bot state error=%s", result.get("error"))
        self._tray.update_menu()

    def schedule_relaunch(self, stage: Path, *, install: Path | None, update: VerifiedUpdate | None) -> None:
        with self._exit_lock:
            if self._exit_requested or self._relaunch_stage is not None:
                raise RuntimeError("Desktop is already exiting.")
            desktop_relaunch.start_worker(stage, self._bridge._profile_root, self._backend.run_intent,
                                          dev_url=self._dev_url, install=install, update=update)
            self._relaunch_stage = stage
            threading.Thread(target=self.exit_application, name="heetkit-desktop-relaunch").start()

    def exit_application(self) -> None:
        with self._exit_lock:
            if self._exit_requested:
                return
            self._exit_requested = True
        try:
            self._backend.close()
            if self._relaunch_stage is not None:
                (self._relaunch_stage / "shutdown-complete").touch()
        except Exception:
            self._logger.exception("Desktop backend shutdown failed")
        finally:
            if self._relaunch_stage is None and isinstance(self._bridge, WebUIBridge):
                if self._bridge._desktop_operation.acquire(blocking=False):
                    try:
                        self._bridge._discard_prepared_update()
                    finally:
                        self._bridge._desktop_operation.release()
            self._tray_refresh_stop.set()
            self._tray.stop()
            if self._window is not None:
                try:
                    self._window.destroy()
                except Exception:
                    self._logger.exception("Could not close desktop window")

    def shutdown(self) -> None:
        self.exit_application()

    def _on_closing(self) -> bool | None:
        if self._exit_requested:
            return None
        if self._tray_started and self._app_settings.snapshot().window.close_to_tray:
            if self._window is not None:
                self._window.hide()
            return False
        return None

    def _on_closed(self) -> None:
        self._window = None
        self.exit_application()

    def _on_minimized(self) -> None:
        if (
            self._tray_started
            and self._app_settings.snapshot().window.minimize_to_tray
            and self._window is not None
        ):
            self._window.hide()


def configure_windows_taskbar(window: Any) -> None:
    """Apply the branded icon to pywebview's native WinForms window."""
    try:
        from System import Action
        from System.Drawing import Icon

        native = window.native

        def set_icon() -> None:
            native.Icon = Icon(str(ICON_ROOT / "icon.ico"))

        if native.InvokeRequired:
            native.Invoke(Action(set_icon))
        else:
            set_icon()
    except Exception:
        get_logger("app.webview.desktop").exception("Could not set Windows taskbar icon")



SETUP_REGISTRY_KEY = r"Software\HeetKit"
SETUP_LANGUAGE_VALUE = "InitialUiLanguage"


def setup_interface_language() -> str | None:
    """Language chosen in Windows Setup (HKCU) for this installed copy; None for portable or other platforms."""
    if sys.platform != "win32" or desktop_relaunch.installed_directory() is None:
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETUP_REGISTRY_KEY) as key:
            value, kind = winreg.QueryValueEx(key, SETUP_LANGUAGE_VALUE)
    except OSError:
        return None
    return value if kind == winreg.REG_SZ and isinstance(value, str) else None


def run_desktop_host(
    settings: Settings,
    frontend_url: str,
    *,
    auto_start: bool | None = None,
    credential_manager: CredentialManager | None = None,
    relaunch_ready: Path | None = None,
) -> None:
    import webview

    if frontend_url.startswith(("http://", "https://")):
        resolve_frontend_url(frontend_url)

    if sys.platform == "win32":
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        result = set_app_id(WINDOWS_APP_ID)
        if result != 0:
            get_logger("app.webview.desktop").warning(
                "Could not set Windows taskbar application identity: %s", result
            )

    app_settings = AppSettingsStore(RuntimePaths.default().app_settings)
    if app_settings.seed_interface_language(setup_interface_language()):
        get_logger("app.webview.desktop").info("Applied the interface language chosen in Setup")
    settings_snapshot = app_settings.snapshot()
    settings = apply_twitch_app_settings(settings, settings_snapshot)
    settings = apply_ai_app_settings(settings, settings_snapshot)
    should_auto_start = resolve_auto_start(settings_snapshot, auto_start)
    backend = AsyncioBackendHost(
        settings,
        auto_start=should_auto_start,
        initial_ai_memory_enabled=settings_snapshot.ai.memory_enabled,
    )
    controller: DesktopController | None = None
    try:
        backend.start()
        bridge = WebUIBridge(
            backend,
            app_settings=app_settings,
            credential_manager=credential_manager,
        )
        development_mode = frontend_url.startswith(("http://", "https://"))
        controller = DesktopController(backend, bridge, app_settings, dev_url=frontend_url if development_mode else None)
        bridge._controller = controller
        bridge._relaunch_ready = relaunch_ready
        window = webview.create_window(
            APPLICATION_NAME,
            frontend_url,
            width=1180,
            height=760,
            min_size=(900, 620),
            hidden=relaunch_ready is None and settings_snapshot.window.start_minimized and sys.platform == "win32",
            background_color="#0b0f17",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("Could not create the desktop window.")
        bridge._window = window
        expose_frontend_operations(window, bridge)
        if sys.platform == "win32":
            window.events.shown += configure_windows_taskbar
        controller.bind_window(window)
        controller.start_tray()
        icon_name = (
            "icon.ico" if sys.platform == "win32" else
            "icon.icns" if sys.platform == "darwin" else
            "icon.png"
        )
        webview.start(
            gui="edgechromium" if sys.platform == "win32" else None,
            debug=development_mode,
            http_server=not development_mode,
            icon=str(ICON_ROOT / icon_name),
        )
    finally:
        if controller is not None:
            controller.shutdown()
        else:
            backend.close()


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == desktop_relaunch.WORKER_FLAG:
        desktop_relaunch.run_worker(Path(sys.argv[2]), int(sys.argv[3]))
        return
    parser = argparse.ArgumentParser(description="HeetKit — Desktop control center for Twitch chat")
    parser.add_argument("--data-dir", type=Path, help="Use an independent profile directory (or HEETKIT_DATA_DIR).")
    parser.add_argument(
        "--dev-url",
        help="Load a running Vite development server instead of built frontend assets.",
    )
    run_override = parser.add_mutually_exclusive_group()
    run_override.add_argument(
        "--stopped",
        action="store_true",
        help="Open the UI with the Twitch bot stopped, overriding the saved preference.",
    )
    run_override.add_argument("--resume-bot", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(desktop_relaunch.READY_FLAG, type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate desktop libraries, configuration and frontend availability without opening the UI.",
    )
    arguments = parser.parse_args()
    if arguments.dev_url:
        try:
            resolve_frontend_url(arguments.dev_url)
        except ValueError as error:
            parser.error(str(error))
    if arguments.data_dir is not None:
        os.environ[DATA_DIR_ENV] = str(arguments.data_dir.expanduser().resolve())
    try:
        ensure_windows_runtime()
        with ExitStack() as guards:
            paths = RuntimePaths.default()
            if not arguments.check:
                if (install := desktop_relaunch.installed_directory()) is not None:
                    guards.enter_context(desktop_relaunch.installation_access(install))
                    desktop_relaunch.remove_finished_runners()
                guards.enter_context(desktop_instance_guard(paths.app_settings))
            settings, credential_manager = load_settings_with_credentials()
            if not arguments.check:
                token_file, database_url = prepare_runtime_data(settings.database_url)
                settings = settings.model_copy(
                    update={"twitch_token_file": token_file, "database_url": database_url}
                )
            configure_logging(settings.log_level)
            frontend_url = resolve_frontend_url(arguments.dev_url)
            if arguments.check:
                logging.getLogger("app.webview").info("Web desktop configuration check completed")
                return
            run_desktop_host(
                settings,
                frontend_url,
                auto_start=False if arguments.stopped else True if arguments.resume_bot else None,
                credential_manager=credential_manager,
                relaunch_ready=arguments.desktop_relaunch_ready,
            )
    except DesktopPrerequisiteError as error:
        if not arguments.check:
            notify_existing_desktop(str(error))
        parser.exit(1, f"ERROR: {error}\n")
    except DesktopAlreadyRunningError as error:
        notify_existing_desktop(str(error))
        parser.exit(1, f"ERROR: {error}\n")
    except DatabaseMigrationError as error:
        if not arguments.check:
            notify_existing_desktop(error.operator_message)
        parser.exit(1, f"ERROR: {error.operator_message}\n")
    except (ValidationError, FileNotFoundError, RuntimeDataError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
