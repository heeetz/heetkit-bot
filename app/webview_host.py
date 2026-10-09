"""pywebview desktop host for the React presentation layer."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import logging
import math
import os
import subprocess
import sys
import threading
import webbrowser
from functools import wraps
from inspect import signature
from urllib.parse import urlsplit
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any, Coroutine

from pydantic import SecretStr, ValidationError

from app.app_settings import AISettings, AppSettings, AppSettingsStore, TwitchSettings
from app.bot_runtime import BotRuntime
from app.command_settings import CommandSettings
from app.commands.registry import command_unavailable_reason
from app.custom_commands import VARIABLES
from app.config.ai_models import GEMINI_MODEL_PRESETS, GEMINI_PROVIDER_NAME
from app.config.ai_language import (
    RESPONSE_LANGUAGES, build_response_language_instruction,
)
from app.config.personalities import AI_PERSONALITY_PROMPTS, build_protected_shared_instructions
from app.config.settings import Settings, TwitchConfigurationError, load_settings_with_credentials
from app.container import Application, build_application
from app.credentials import CredentialError, CredentialManager, CredentialName, CredentialStore
from app.desktop_instance import (
    DesktopAlreadyRunningError,
    desktop_instance_guard,
    notify_existing_desktop,
)
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
from app.services.updates import RELEASE_PAGE_URL, UpdateCheckError, check_for_updates
from app.windows_runtime import DesktopPrerequisiteError, ensure_windows_runtime
from app.twitch.client import OAUTH_REDIRECT_URI
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
APPLICATION_NAME = "HeetKit"
APPLICATION_SUBTITLE = "Desktop control center for Twitch chat"
EXTERNAL_LINKS = {
    # Repository address remains unchanged until a separately requested remote rename.
    "repository": "https://github.com/heeetz/twitch-bot",
    "license": "https://github.com/heeetz/twitch-bot/blob/main/LICENSE",
    "third_party_notices": "https://github.com/heeetz/twitch-bot/blob/main/THIRD_PARTY_NOTICES.md",
    "author_twitch": "https://www.twitch.tv/heet_ok",
    "twitch_developer_console": "https://dev.twitch.tv/console/apps",
    "releases": RELEASE_PAGE_URL,
}

# Register functions by exact name; never give pywebview an object to traverse.
FRONTEND_OPERATIONS = (
    "get_app_status", "get_about_info", "check_for_updates", "get_commands", "get_custom_commands",
    "get_filters", "get_ai_status", "get_personalities", "get_recent_logs",
    "apply_command_settings", "save_command_settings", "reset_command_settings",
    "apply_command_responses", "save_command_responses", "reset_command_responses",
    "save_custom_command", "delete_custom_command", "apply_filters", "save_filters", "test_filters",
    "set_ai_enabled", "set_ai_memory_enabled", "apply_personality", "create_personality",
    "rename_personality", "delete_personality", "set_active_personality",
    "save_personality", "reset_personality", "apply_profile_instructions",
    "save_profile_instructions", "reset_profile_instructions", "get_app_settings",
    "get_profile_info", "open_profile_folder", "update_app_settings",
    "get_twitch_settings", "update_twitch_settings", "save_twitch_preset",
    "delete_twitch_preset", "reconnect_twitch", "get_credentials",
    "get_ai_provider_settings", "update_ai_provider_settings", "discover_gemini_models",
    "get_ai_language_settings", "update_ai_language_settings",
    "replace_credential", "remove_credential", "test_credential", "start_bot", "stop_bot",
    "open_external_link",
)


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
            raise RuntimeError("Desktop backend startup failed.") from self._startup_error

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
            loop.run_until_complete(bot_runtime.startup())
            if self._auto_start:
                try:
                    loop.run_until_complete(bot_runtime.start_bot())
                except TwitchConfigurationError as error:
                    self._logger.warning("Automatic Twitch start skipped: %s", error)
            self._ready.set()
            loop.run_forever()
        except Exception as error:
            self._startup_error = error
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
            self._bot_runtime.shutdown(),
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
                    self._shutdown_future = self.submit(self._bot_runtime.shutdown())
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


class WebUIBridge:
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
        self._profile_root = RuntimePaths.default().root.resolve()

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

    async def _save_ai_memory_enabled(self, enabled: bool) -> None:
        """Persist and apply AI memory as one backend-loop transaction."""
        if self._app_settings is not None:
            self._app_settings.update_ai_memory(enabled=enabled)
        self._backend.application.services.runtime_state.set_ai_memory_enabled(enabled)

    async def _save_ai_provider_models(
        self,
        selected_model: object,
        fallback_model: object,
    ) -> AISettings:
        """Persist and apply Gemini models in backend-loop submission order."""
        if self._app_settings is None:
            raise RuntimeError("Desktop settings are not configured.")
        updated = self._app_settings.update_ai_models(
            selected_model=selected_model,
            fallback_model=fallback_model,
        )
        application_settings = self._backend.application.settings
        application_settings.gemini_model = updated.ai.selected_model
        application_settings.gemini_fallback_model = updated.ai.fallback_model
        return updated.ai

    async def _save_ai_response_language(
        self, mode: object, allowed_languages: object, fallback_language: object,
    ) -> None:
        """Persist before publishing one immutable policy on the backend loop."""
        if self._app_settings is None:
            raise RuntimeError("Desktop settings are not configured.")
        updated = self._app_settings.update_ai_response_language(
            mode=mode, allowed_languages=allowed_languages, fallback_language=fallback_language,
        )
        self._backend.application.settings.ai_response_language = updated.ai.response_language

    def get_app_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        running, uptime = runtime_state.status()
        return {
            "running": running,
            "twitch_connected": runtime_state.twitch_connected,
            "twitch_connection_state": runtime_state.twitch_connection_state,
            "uptime_seconds": uptime,
            "channel": application.settings.twitch_channel,
            "account": application.settings.twitch_bot_username,
        }

    def get_about_info(self) -> dict[str, str]:
        return {
            "application_name": APPLICATION_NAME,
            "application_subtitle": APPLICATION_SUBTITLE,
            "version": application_version(),
            "author": "heeetz",
            "author_twitch": "@heet_ok",
            "repository_url": EXTERNAL_LINKS["repository"],
            "discord_contact": "de.tected",
            "license_name": "Apache-2.0",
            "license_url": EXTERNAL_LINKS["license"],
            "third_party_notices_url": EXTERNAL_LINKS["third_party_notices"],
        }

    def get_profile_info(self) -> dict[str, str]:
        return {"path": str(self._profile_root)}

    def check_for_updates(self) -> dict[str, object]:
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
        return {"ok": True, "current_version": current_version, **release}

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

    def open_external_link(self, destination: object) -> dict[str, object]:
        if not isinstance(destination, str) or destination not in (*EXTERNAL_LINKS, "twitch_authorization"):
            return {"ok": False, "error": "That external link is not available."}
        url = EXTERNAL_LINKS.get(destination, "")
        if destination == "twitch_authorization":
            application = self._backend.application
            runtime_state = application.services.runtime_state
            if not runtime_state.status()[0]:
                return {"ok": False, "error": "Start Bot before authorizing Twitch."}
            if runtime_state.twitch_connection_state != "auth_required":
                return {"ok": False, "error": "Twitch authorization is not currently required."}
            try:
                application.settings.validate_twitch_configuration()
            except TwitchConfigurationError as error:
                return {"ok": False, "error": str(error)}
            if self._app_settings is not None and self._twitch_identity_requires_restart(
                self._app_settings.snapshot().twitch
            ):
                return {"ok": False, "error": "Restart the application to apply the saved Twitch client ID and bot identity."}
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

    def get_commands(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        commands = []
        for definition in application.registry.definitions():
            settings = runtime_state.get_command_settings(definition.name)
            defaults = runtime_state.get_command_default_settings(definition.name)
            unavailable_reason = command_unavailable_reason(definition, application.services)
            fun_settings = getattr(application, "fun_settings", None)
            commands.append(
                {
                    "name": definition.name,
                    "aliases": list(definition.aliases),
                    "enabled": settings.enabled,
                    "available": unavailable_reason is None,
                    "unavailable_reason": unavailable_reason,
                    "response_pool": fun_settings.snapshot(definition.name)
                    if definition.name in ("fate", "tg") and fun_settings else None,
                    "permission": settings.permission.name,
                    "cooldown": {
                        "per_user_seconds": settings.cooldown.per_user_seconds,
                        "global_seconds": settings.cooldown.global_seconds,
                    },
                    "hidden": definition.hidden,
                    "default_settings": self._serialize_command_settings(defaults),
                    "saved": runtime_state.command_settings_are_saved(definition.name),
                    "has_saved_override": runtime_state.has_saved_command_override(
                        definition.name
                    ),
                }
            )
        return {
            "command_prefix": application.settings.command_prefix,
            "permissions": [permission.name for permission in Permission],
            "commands": commands,
        }

    def _command_response_action(self, name: object, responses: object, action: str) -> dict[str, object]:
        store = getattr(self._backend.application, "fun_settings", None)
        if name not in ("fate", "tg") or store is None:
            return {"ok": False, "error": "This command has no editable responses."}
        try:
            if action == "reset":
                store.reset(name)
            elif action == "save":
                store.save(responses, name)
            else:
                store.apply(responses, name)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not %s command responses", action)
            return {"ok": False, "error": "Could not save command responses."}
        return {"ok": True}

    def apply_command_responses(self, name: object, responses: object) -> dict[str, object]:
        return self._command_response_action(name, responses, "apply")

    def save_command_responses(self, name: object, responses: object) -> dict[str, object]:
        return self._command_response_action(name, responses, "save")

    def reset_command_responses(self, name: object) -> dict[str, object]:
        return self._command_response_action(name, None, "reset")

    def get_custom_commands(self) -> dict[str, object]:
        application = self._backend.application
        return {
            "command_prefix": application.settings.command_prefix,
            "permissions": [permission.name for permission in Permission],
            "variables": list(VARIABLES),
            "commands": [
                {**command.to_json(), "response_mode": command.response_mode}
                for command in application.custom_commands.list()
            ],
        }

    def get_filters(self) -> dict[str, object]:
        return get_filter_settings(self._backend.application.services.filter_manager)

    async def _change_filters(self, payload: object, *, save: bool) -> None:
        parsed = validate_filter_input(payload)
        manager = self._backend.application.services.filter_manager
        if save:
            save_filter_settings(manager, parsed)
        else:
            apply_filter_settings(manager, parsed)

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

    def apply_filters(self, payload: object) -> dict[str, object]:
        return self._filter_action(payload, save=False)

    def save_filters(self, payload: object) -> dict[str, object]:
        return self._filter_action(payload, save=True)

    async def _test_filters(
        self, text: object, source: object, payload: object
    ) -> dict[str, object]:
        # Serialize with Apply/Save and live filtering on the owning backend loop.
        return evaluate_filter_settings(
            self._backend.application.services.filter_manager, text, source, payload
        )

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

    def save_custom_command(self, command: object) -> dict[str, object]:
        try:
            saved = self._backend.application.custom_commands.save(command)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save custom command")
            return {"ok": False, "error": "Could not save custom command."}
        self._logger.info("Custom command saved name=%s", saved.name)
        return {"ok": True}

    def delete_custom_command(self, identifier: str) -> dict[str, object]:
        try:
            self._backend.application.custom_commands.delete(identifier)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not delete custom command")
            return {"ok": False, "error": "Could not delete custom command."}
        self._logger.info("Custom command deleted id=%s", identifier)
        return {"ok": True}

    @staticmethod
    def _serialize_command_settings(settings: CommandSettings) -> dict[str, object]:
        return {
            "enabled": settings.enabled,
            "permission": settings.permission.name,
            "cooldown": {
                "per_user_seconds": settings.cooldown.per_user_seconds,
                "global_seconds": settings.cooldown.global_seconds,
            },
        }

    @staticmethod
    def _parse_command_settings(
        enabled: object,
        per_user_seconds: object,
        global_seconds: object,
        permission: object,
    ) -> tuple[bool, CooldownPolicy, Permission]:
        if type(enabled) is not bool:
            raise ValueError("Enabled must be a boolean.")
        values = (per_user_seconds, global_seconds)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in values
        ):
            raise ValueError("Cooldown values must be non-negative numbers.")
        if not isinstance(permission, str):
            raise ValueError("Permission must be a valid permission name.")
        try:
            parsed_permission = Permission[permission]
        except KeyError as error:
            raise ValueError("Permission must be a valid permission name.") from error
        return (
            enabled,
            CooldownPolicy(
                per_user_seconds=float(per_user_seconds),
                global_seconds=float(global_seconds),
            ),
            parsed_permission,
        )

    def apply_command_settings(
        self,
        command_name: str,
        enabled: object,
        per_user_seconds: object,
        global_seconds: object,
        permission: object,
    ) -> dict[str, object]:
        try:
            parsed_enabled, cooldown, parsed_permission = self._parse_command_settings(
                enabled,
                per_user_seconds,
                global_seconds,
                permission,
            )
            self._backend.application.services.runtime_state.apply_command_settings(
                command_name,
                enabled=parsed_enabled,
                cooldown=cooldown,
                permission=parsed_permission,
            )
        except KeyError:
            return {"ok": False, "error": "Unknown command."}
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        self._logger.info(
            "Command runtime settings applied command=%s",
            command_name,
            extra={
                "event_kind": "settings.command",
                "event_command": command_name,
                "event_action": "apply",
            },
        )
        return {"ok": True}

    def save_command_settings(
        self,
        command_name: str,
        enabled: object,
        per_user_seconds: object,
        global_seconds: object,
        permission: object,
    ) -> dict[str, object]:
        try:
            parsed_enabled, cooldown, parsed_permission = self._parse_command_settings(
                enabled,
                per_user_seconds,
                global_seconds,
                permission,
            )
            self._backend.application.services.runtime_state.save_command_settings(
                command_name,
                enabled=parsed_enabled,
                cooldown=cooldown,
                permission=parsed_permission,
            )
        except KeyError:
            return {"ok": False, "error": "Unknown command."}
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save command settings command=%s", command_name)
            return {"ok": False, "error": "Could not save command settings."}
        self._logger.info(
            "Command settings saved command=%s",
            command_name,
            extra={
                "event_kind": "settings.command",
                "event_command": command_name,
                "event_action": "save",
            },
        )
        return {"ok": True}

    def reset_command_settings(self, command_name: str) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.reset_command_settings(
                command_name
            )
        except (KeyError, TypeError):
            return {"ok": False, "error": "Unknown command."}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset command settings command=%s", command_name)
            return {"ok": False, "error": "Could not reset command settings."}
        self._logger.info(
            "Command settings reset command=%s",
            command_name,
            extra={
                "event_kind": "settings.command",
                "event_command": command_name,
                "event_action": "reset",
            },
        )
        return {"ok": True}

    def get_ai_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        return {
            "enabled": runtime_state.ai_enabled,
            "available": bool(getattr(getattr(application.services, "ai", None), "is_available", False)),
            "memory_enabled": runtime_state.ai_memory_enabled,
            "active_personality": runtime_state.active_ai_personality,
            "available_personalities": list(runtime_state.available_personalities),
            "model": application.settings.gemini_model,
        }

    def get_personalities(self) -> dict[str, object]:
        runtime_state = self._backend.application.services.runtime_state
        current, saved = runtime_state.get_personality_settings_snapshot()
        return {
            "active_personality": current.active_personality,
            "active_personality_saved": current.active_personality == saved.active_personality,
            "profile_instructions": current.profile_instructions,
            "profile_instructions_saved": current.profile_instructions == saved.profile_instructions,
            "protected_shared_instructions": build_protected_shared_instructions(
                self._backend.application.settings.ai_response_language,
            ),
            "personalities": [
                {
                    "name": name,
                    "is_builtin": name in AI_PERSONALITY_PROMPTS,
                    "prompt": prompt,
                    "built_in_prompt": AI_PERSONALITY_PROMPTS.get(name, ""),
                    "prompt_saved": prompt == saved.overrides.get(name, AI_PERSONALITY_PROMPTS.get(name, "")),
                    "has_saved_override": name in saved.overrides,
                }
                for name, prompt in current.overrides.items()
            ],
        }

    def apply_profile_instructions(self, prompt: object) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.apply_profile_instructions(prompt)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        self._log_profile_instructions_action("apply")
        return {"ok": True}

    def save_profile_instructions(self, prompt: object) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.save_profile_instructions(prompt)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI profile instructions")
            return {"ok": False, "error": "Could not save AI profile instructions."}
        self._log_profile_instructions_action("save")
        return {"ok": True}

    def reset_profile_instructions(self) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.reset_profile_instructions()
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset AI profile instructions")
            return {"ok": False, "error": "Could not reset AI profile instructions."}
        self._log_profile_instructions_action("reset")
        return {"ok": True}

    def _log_profile_instructions_action(self, action: str) -> None:
        self._logger.info(
            "AI profile instructions updated action=%s", action,
            extra={
                "event_kind": "settings.ai",
                "event_setting": "profile_instructions",
                "event_action": action,
            },
        )

    @staticmethod
    def _validate_toggle(enabled: object) -> bool:
        if type(enabled) is not bool:
            raise ValueError("Enabled must be a boolean.")
        return enabled

    def set_ai_enabled(self, enabled: object) -> dict[str, object]:
        try:
            parsed_enabled = self._validate_toggle(enabled)
            self._backend.application.services.runtime_state.set_ai_enabled(
                parsed_enabled
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        self._logger.info(
            "AI command runtime state changed enabled=%s",
            parsed_enabled,
            extra={
                "event_kind": "settings.ai",
                "event_setting": "enabled",
                "event_action": "update",
            },
        )
        return {"ok": True}

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

    def apply_personality(self, personality: object, prompt: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.apply_ai_personality(
                personality,
                prompt,
            )
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        self._logger.info(
            "AI personality applied name=%s",
            personality,
            extra={
                "event_kind": "settings.personality",
                "event_setting": str(personality),
                "event_action": "apply",
            },
        )
        return {"ok": True}

    def create_personality(self, name: object, prompt: object) -> dict[str, object]:
        try:
            name = self._backend.application.services.runtime_state.create_ai_personality(name, prompt)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not create AI personality")
            return {"ok": False, "error": "Could not create AI personality."}
        return {"ok": True, "name": name}

    def rename_personality(self, personality: object, name: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            name = self._backend.application.services.runtime_state.rename_ai_personality(personality, name)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not rename AI personality")
            return {"ok": False, "error": "Could not rename AI personality."}
        return {"ok": True, "name": name}

    def delete_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.delete_ai_personality(personality)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not delete AI personality")
            return {"ok": False, "error": "Could not delete AI personality."}
        return {"ok": True}

    def set_active_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.save_active_ai_personality(personality)
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not set active AI personality")
            return {"ok": False, "error": "Could not set active AI personality."}
        return {"ok": True}

    def save_personality(self, personality: object, prompt: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.save_ai_personality(
                personality,
                prompt,
            )
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not save AI personality name=%s", personality)
            return {"ok": False, "error": "Could not save AI personality."}
        self._logger.info(
            "AI personality override saved name=%s",
            personality,
            extra={
                "event_kind": "settings.personality",
                "event_setting": str(personality),
                "event_action": "save",
            },
        )
        return {"ok": True}

    def reset_personality(self, personality: object) -> dict[str, object]:
        try:
            if not isinstance(personality, str):
                raise ValueError("Unknown AI personality.")
            self._backend.application.services.runtime_state.reset_ai_personality(
                personality
            )
        except (TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset AI personality name=%s", personality)
            return {"ok": False, "error": "Could not reset AI personality."}
        self._logger.info(
            "AI personality override reset name=%s",
            personality,
            extra={
                "event_kind": "settings.personality",
                "event_setting": str(personality),
                "event_action": "reset",
            },
        )
        return {"ok": True}

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
                "requires_restart": self._twitch_identity_requires_restart(local),
                "running": runtime_state.status()[0],
                "connected": runtime_state.twitch_connected,
                "oauth_token_available": Path(
                    application.settings.twitch_token_file
                ).is_file(),
                "oauth_callback_url": OAUTH_REDIRECT_URI,
                "has_local_override": (
                    local.channel is not None
                    and local.channel_user_id is not None
                ),
            },
        }

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
            "requires_restart": self._twitch_identity_requires_restart(updated.twitch),
        }

    def _twitch_identity_requires_restart(self, local: TwitchSettings) -> bool:
        active = self._backend.application.settings
        return any(
            value is not None and value != getattr(active, f"twitch_{name}", "")
            for name, value in (
                ("client_id", local.client_id), ("bot_username", local.bot_username),
                ("bot_user_id", local.bot_user_id),
            )
        )

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

    def reconnect_twitch(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        application = self._backend.application
        local = self._app_settings.snapshot().twitch
        if self._twitch_identity_requires_restart(local):
            return {"ok": False, "error": "Restart the application to apply the saved Twitch client ID and bot identity."}
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
        except TwitchConfigurationError as error:
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

    def get_ai_language_settings(self) -> dict[str, object]:
        language = self._backend.application.settings.ai_response_language
        return {
            "ok": True,
            "settings": {
                **asdict(language), "allowed_languages": list(language.allowed_languages),
            },
            "languages": [{"code": code, "label": label} for code, label in RESPONSE_LANGUAGES.items()],
            "active_policy": build_response_language_instruction(language),
        }

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

    def get_ai_provider_settings(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        application = self._backend.application
        credential = None
        if self._credential_manager is not None:
            credential = next(
                (
                    status.serialize()
                    for status in self._credential_manager.statuses()
                    if status.name == "gemini_api_key"
                ),
                None,
            )
        return {
            "ok": True,
            "settings": {
                "provider": GEMINI_PROVIDER_NAME,
                "selected_model": application.settings.gemini_model,
                "fallback_model": application.settings.gemini_fallback_model,
                "presets": [preset.serialize() for preset in GEMINI_MODEL_PRESETS],
                "credential": credential,
            },
        }

    def update_ai_provider_settings(
        self,
        selected_model: object,
        fallback_model: object,
    ) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            updated = self._wait_for_backend(
                self._save_ai_provider_models(selected_model, fallback_model),
                operation="save_ai_models",
                timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "error": "Saving Gemini model settings timed out. Check Logs for details.",
            }
        except OSError:
            self._logger.exception("Could not save Gemini model settings")
            return {"ok": False, "error": "Could not save Gemini model settings."}
        except Exception:
            self._logger.exception("Could not save Gemini model settings")
            return {"ok": False, "error": "Could not save Gemini model settings."}
        self._logger.info(
            "Gemini model settings saved selected_model=%s fallback_model=%s",
            updated.selected_model,
            updated.fallback_model,
            extra={
                "event_kind": "settings.ai_model",
                "event_provider": "Google Gemini",
                "event_model": str(updated.selected_model),
                "event_action": "save",
            },
        )
        return {"ok": True}

    def discover_gemini_models(self) -> dict[str, object]:
        service = self._backend.application.services.ai
        discover = getattr(service, "discover_models", None)
        if discover is None:
            return {"ok": False, "error": "Gemini model discovery is unavailable."}
        try:
            models = self._wait_for_backend(
                discover(),
                operation="discover_gemini_models",
                timeout=BRIDGE_MODEL_DISCOVERY_TIMEOUT_SECONDS,
            )
        except BridgeOperationTimedOut:
            return {
                "ok": False,
                "error": "Gemini model discovery timed out. Check Logs for details.",
            }
        except Exception:
            self._logger.exception("Gemini model discovery failed")
            return {"ok": False, "error": "Could not discover Gemini models."}
        return {"ok": True, "models": models}

    def get_credentials(self) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        return {
            "ok": True,
            "credentials": [
                status.serialize() for status in self._credential_manager.statuses()
            ],
        }

    async def _refresh_gemini_credential(self) -> None:
        value = self._credential_manager.effective_value(CredentialName.GEMINI_API_KEY)
        self._backend.application.settings.gemini_api_key = SecretStr(value) if value else None

    def _apply_credential_change(self, name: CredentialName) -> None:
        if name is CredentialName.GEMINI_API_KEY:
            self._wait_for_backend(
                self._refresh_gemini_credential(), operation="apply_gemini_credential",
                timeout=BRIDGE_SETTINGS_TIMEOUT_SECONDS,
            )

    def replace_credential(self, name: object, value: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            self._credential_manager.replace(parsed_name.value, value)
            self._apply_credential_change(parsed_name)
        except BridgeOperationTimedOut:
            return {"ok": False, "error": "Credential stored securely. Restart to apply it; the backend timed out."}
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
        return {"ok": True}

    def remove_credential(self, name: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            removed = self._credential_manager.remove(parsed_name.value)
            self._apply_credential_change(parsed_name)
        except BridgeOperationTimedOut:
            return {"ok": False, "error": "Credential removed. Restart to apply the fallback; the backend timed out."}
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
        return {"ok": True, "changed": removed}

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

    def get_recent_logs(self, after_id: int = 0, limit: int = 200) -> dict[str, object]:
        safe_after_id = after_id if type(after_id) is int and after_id >= 0 else 0
        safe_limit = limit if type(limit) is int else 200
        safe_limit = min(200, max(1, safe_limit))
        return {
            "entries": self._log_buffer.recent(
                after_id=safe_after_id,
                limit=safe_limit,
            )
        }

    def start_bot(self) -> dict[str, object]:
        try:
            started = self._wait_for_backend(
                self._backend.bot_runtime.start_bot(),
                operation="start_bot",
                timeout=BRIDGE_BOT_START_TIMEOUT_SECONDS,
            )
        except TwitchConfigurationError as error:
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
        return {"ok": True, "changed": started}

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
        return {"ok": True, "changed": stopped}


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

    def guarded(name: str) -> Any:
        operation = getattr(bridge, name)
        @wraps(operation)
        def call(*args: Any, **kwargs: Any) -> Any:
            if trusted_origin is None or _frontend_origin(window.get_current_url()) != trusted_origin:
                return {"ok": False, "error": "This page cannot access the application bridge."}
            return operation(*args, **kwargs)

        call.__signature__ = signature(operation)
        call.__name__ = name
        return call

    window.expose(*(guarded(name) for name in FRONTEND_OPERATIONS))


def apply_twitch_app_settings(settings: Settings, app_settings: AppSettings) -> Settings:
    twitch = app_settings.twitch
    overrides = {
        f"twitch_{name}": value
        for name in ("client_id", "bot_username", "bot_user_id", "channel", "channel_user_id")
        if (value := getattr(twitch, name)) is not None
    }
    return settings.model_copy(update=overrides)


def apply_ai_app_settings(settings: Settings, app_settings: AppSettings) -> Settings:
    ai = app_settings.ai
    overrides = {"ai_response_language": ai.response_language}
    if ai.selected_model is not None and ai.fallback_model is not None:
        overrides.update(gemini_model=ai.selected_model, gemini_fallback_model=ai.fallback_model)
    if ai.cooldown_bypass_user_id is not None:
        overrides["ai_cooldown_bypass_user_id"] = ai.cooldown_bypass_user_id
    return settings.model_copy(update=overrides) if overrides else settings


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
        self._tray = tray or SystemTray(
            on_open=self.open_window,
            on_toggle_bot=self.toggle_bot,
            on_exit=self.exit_application,
            is_bot_running=self.is_bot_running,
        )

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

    def exit_application(self) -> None:
        with self._exit_lock:
            if self._exit_requested:
                return
            self._exit_requested = True
        try:
            self._backend.close()
        except Exception:
            self._logger.exception("Desktop backend shutdown failed")
        finally:
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


def run_desktop_host(
    settings: Settings,
    frontend_url: str,
    *,
    auto_start: bool | None = None,
    credential_manager: CredentialManager | None = None,
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
        controller = DesktopController(backend, bridge, app_settings)
        window = webview.create_window(
            APPLICATION_NAME,
            frontend_url,
            width=1180,
            height=760,
            min_size=(900, 620),
            hidden=settings_snapshot.window.start_minimized and sys.platform == "win32",
            background_color="#0b0f17",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("Could not create the desktop window.")
        expose_frontend_operations(window, bridge)
        if sys.platform == "win32":
            window.events.shown += configure_windows_taskbar
        controller.bind_window(window)
        controller.start_tray()
        development_mode = frontend_url.startswith(("http://", "https://"))
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
    parser = argparse.ArgumentParser(description="HeetKit — Desktop control center for Twitch chat")
    parser.add_argument("--data-dir", type=Path, help="Use an independent profile directory (or HEETKIT_DATA_DIR).")
    parser.add_argument(
        "--dev-url",
        help="Load a running Vite development server instead of built frontend assets.",
    )
    parser.add_argument(
        "--stopped",
        action="store_true",
        help="Open the UI with the Twitch bot stopped, overriding the saved preference.",
    )
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
                guards.enter_context(desktop_instance_guard(paths.app_settings))
                if sys.platform == "win32" and not paths.brand_migration_marker.exists():
                    # Legacy compatibility: the former desktop could also be
                    # running against this same explicit profile directory.
                    guards.enter_context(desktop_instance_guard(paths.app_settings, legacy_identity=True))
                if paths.is_default_profile and not paths.brand_migration_marker.exists() and paths.former_default_root.is_dir():
                    guards.enter_context(desktop_instance_guard(
                        paths.former_default_root / "config" / "app_settings.json",
                        legacy_identity=True,
                    ))
            settings, credential_manager = (
                load_settings_with_credentials(CredentialStore(migrate_legacy=False))
                if arguments.check else load_settings_with_credentials()
            )
            if not arguments.check:
                token_file, database_url = prepare_runtime_data(
                    settings.twitch_token_file, settings.database_url
                )
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
                auto_start=False if arguments.stopped else None,
                credential_manager=credential_manager,
            )
    except DesktopPrerequisiteError as error:
        if not arguments.check:
            notify_existing_desktop(str(error))
        parser.exit(1, f"ERROR: {error}\n")
    except DesktopAlreadyRunningError as error:
        notify_existing_desktop(str(error))
        parser.exit(1, f"ERROR: {error}\n")
    except (ValidationError, FileNotFoundError, RuntimeDataError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
