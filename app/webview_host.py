"""pywebview desktop host for the React presentation layer."""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Coroutine

from pydantic import ValidationError

from app.app_settings import AppSettings, AppSettingsStore
from app.bot_runtime import BotRuntime
from app.command_settings import CommandSettings
from app.config.settings import Settings, load_settings_with_credentials
from app.container import Application, build_application
from app.credentials import CredentialError, CredentialManager
from app.system_tray import SystemTray
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.utils.logging import (
    RecentLogBuffer,
    configure_logging,
    get_logger,
    get_recent_log_buffer,
)
from config import APP_SETTINGS_PATH


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ENTRYPOINT = PROJECT_ROOT / "frontend" / "dist" / "index.html"


class AsyncioBackendHost:
    """Own the application and its single asyncio loop on a background thread."""

    def __init__(
        self,
        settings: Settings,
        *,
        auto_start: bool = True,
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
            name="twitch-bot-asyncio",
            daemon=False,
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
                loop.run_until_complete(bot_runtime.start_bot())
            self._ready.set()
            loop.run_forever()
        except Exception as error:
            self._startup_error = error
            self._ready.set()
            self._logger.exception("Desktop backend failed")
        finally:
            try:
                if self._bot_runtime is not None:
                    loop.run_until_complete(self._bot_runtime.shutdown())
            finally:
                loop.close()

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        loop = self._loop
        if loop is None or not loop.is_running():
            coroutine.close()
            raise RuntimeError("Desktop backend is not running.")
        return asyncio.run_coroutine_threadsafe(coroutine, loop)

    def close(self, timeout: float = 20.0) -> None:
        thread = self._thread
        loop = self._loop
        if thread is None or loop is None:
            return
        try:
            if loop.is_running() and self._bot_runtime is not None:
                future = self.submit(self._bot_runtime.shutdown())
                future.result(timeout=timeout)
        finally:
            if loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=timeout)
        if thread.is_alive():
            raise TimeoutError("Desktop backend shutdown timed out.")
        self._thread = None


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

    def get_app_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        running, uptime = runtime_state.status()
        return {
            "running": running,
            "twitch_connected": runtime_state.twitch_connected,
            "uptime_seconds": uptime,
            "channel": application.settings.twitch_channel,
            "account": application.settings.twitch_bot_username,
        }

    def get_commands(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        commands = []
        for definition in application.registry.definitions():
            settings = runtime_state.get_command_settings(definition.name)
            defaults = runtime_state.get_command_default_settings(definition.name)
            commands.append(
                {
                    "name": definition.name,
                    "aliases": list(definition.aliases),
                    "enabled": settings.enabled,
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
        self._logger.info("Command runtime settings applied command=%s", command_name)
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
        self._logger.info("Command settings saved command=%s", command_name)
        return {"ok": True}

    def reset_command_settings(self, command_name: str) -> dict[str, object]:
        try:
            self._backend.application.services.runtime_state.reset_command_settings(
                command_name
            )
        except (KeyError, TypeError):
            return {"ok": False, "error": "Unknown command."}
        except (OSError, RuntimeError):
            self._logger.exception("Could not reset command settings command=%s", command_name)
            return {"ok": False, "error": "Could not reset command settings."}
        self._logger.info("Command settings reset command=%s", command_name)
        return {"ok": True}

    def get_ai_status(self) -> dict[str, object]:
        application = self._backend.application
        runtime_state = application.services.runtime_state
        return {
            "enabled": runtime_state.ai_enabled,
            "memory_enabled": runtime_state.ai_memory_enabled,
            "active_personality": runtime_state.active_ai_personality,
            "available_personalities": list(runtime_state.available_personalities),
            "model": application.settings.gemini_model,
        }

    def get_personalities(self) -> dict[str, object]:
        runtime_state = self._backend.application.services.runtime_state
        return {
            "active_personality": runtime_state.active_ai_personality,
            "active_personality_saved": runtime_state.active_ai_personality_is_saved,
            "personalities": [
                {
                    "name": name,
                    "prompt": runtime_state.get_ai_personality_prompt(name),
                    "built_in_prompt": runtime_state.get_builtin_ai_personality_prompt(name),
                    "prompt_saved": runtime_state.personality_prompt_is_saved(name),
                    "has_saved_override": runtime_state.has_saved_personality_override(
                        name
                    ),
                }
                for name in runtime_state.available_personalities
            ],
        }

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
        self._logger.info("AI command runtime state changed enabled=%s", parsed_enabled)
        return {"ok": True}

    def set_ai_memory_enabled(self, enabled: object) -> dict[str, object]:
        try:
            parsed_enabled = self._validate_toggle(enabled)
            if self._app_settings is not None:
                self._app_settings.update_ai_memory(enabled=parsed_enabled)
            self._backend.application.services.runtime_state.set_ai_memory_enabled(
                parsed_enabled
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save AI memory setting")
            return {"ok": False, "error": "Could not save AI memory setting."}
        self._logger.info("AI memory setting changed enabled=%s", parsed_enabled)
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
        self._logger.info("AI personality applied name=%s", personality)
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
        self._logger.info("AI personality override saved name=%s", personality)
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
        self._logger.info("AI personality override reset name=%s", personality)
        return {"ok": True}

    def get_app_settings(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        settings = self._app_settings.snapshot()
        return {
            "ok": True,
            "settings": {
                "start_minimized": settings.window.start_minimized,
                "minimize_to_tray": settings.window.minimize_to_tray,
                "close_to_tray": settings.window.close_to_tray,
            },
        }

    def update_app_settings(
        self,
        start_minimized: object,
        minimize_to_tray: object,
        close_to_tray: object,
    ) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            self._app_settings.update_window(
                start_minimized=start_minimized,
                minimize_to_tray=minimize_to_tray,
                close_to_tray=close_to_tray,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            self._logger.exception("Could not save desktop settings")
            return {"ok": False, "error": "Could not save desktop settings."}
        self._logger.info("Desktop application settings saved")
        return {"ok": True}

    def get_twitch_settings(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        application = self._backend.application
        runtime_state = application.services.runtime_state
        local = self._app_settings.snapshot().twitch
        return {
            "ok": True,
            "settings": {
                "target_channel": local.channel or application.settings.twitch_channel,
                "target_channel_user_id": (
                    local.channel_user_id
                    or application.settings.twitch_channel_user_id
                ),
                "active_channel": application.settings.twitch_channel,
                "bot_username": application.settings.twitch_bot_username,
                "bot_user_id": application.settings.twitch_bot_user_id,
                "running": runtime_state.status()[0],
                "connected": runtime_state.twitch_connected,
                "oauth_token_available": Path(
                    application.settings.twitch_token_file
                ).is_file(),
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
    ) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        try:
            updated = self._app_settings.update_twitch(
                channel=target_channel,
                channel_user_id=target_channel_user_id,
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
        self._logger.info("Twitch target channel settings saved")
        return {"ok": True, "requires_reconnect": requires_reconnect}

    def reconnect_twitch(self) -> dict[str, object]:
        if self._app_settings is None:
            return {"ok": False, "error": "Desktop settings are not configured."}
        application = self._backend.application
        local = self._app_settings.snapshot().twitch
        channel = local.channel or application.settings.twitch_channel
        channel_user_id = (
            local.channel_user_id or application.settings.twitch_channel_user_id
        )
        try:
            future = self._backend.submit(
                self._backend.bot_runtime.reconnect_twitch(
                    channel=channel,
                    channel_user_id=channel_user_id,
                )
            )
            reconnected = future.result(timeout=30)
        except Exception as error:
            self._logger.warning(
                "Twitch reconnect failed error_type=%s",
                type(error).__name__,
            )
            return {"ok": False, "error": "Could not reconnect Twitch."}
        self._logger.info("Twitch target settings applied reconnected=%s", reconnected)
        return {"ok": True, "changed": reconnected}

    def get_credentials(self) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        return {
            "ok": True,
            "credentials": [
                status.serialize() for status in self._credential_manager.statuses()
            ],
        }

    def replace_credential(self, name: object, value: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            self._credential_manager.replace(parsed_name.value, value)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except CredentialError as error:
            self._logger.warning(
                "Credential replacement failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid",
                type(error).__name__,
            )
            return {"ok": False, "error": str(error)}
        self._logger.info("Credential replaced name=%s", parsed_name.value)
        return {"ok": True}

    def remove_credential(self, name: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            removed = self._credential_manager.remove(parsed_name.value)
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
            self._logger.info("Credential removed name=%s", parsed_name.value)
        return {"ok": True, "changed": removed}

    def test_credential(self, name: object) -> dict[str, object]:
        if self._credential_manager is None:
            return {"ok": False, "error": "Credential storage is not configured."}
        try:
            parsed_name = self._credential_manager.parse_name(name)
            application = self._backend.application
            future = self._backend.submit(
                self._credential_manager.test(
                    parsed_name.value,
                    http_client=application.http_client,
                    twitch_client_id=application.settings.twitch_client_id,
                )
            )
            future.result(timeout=15)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except CredentialError as error:
            self._logger.warning(
                "Credential test failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid",
                type(error).__name__,
            )
            return {"ok": False, "error": str(error)}
        except Exception as error:
            self._logger.warning(
                "Credential test failed name=%s error_type=%s",
                name if isinstance(name, str) else "invalid",
                type(error).__name__,
            )
            return {"ok": False, "error": "Credential test failed."}
        self._logger.info("Credential test passed name=%s", parsed_name.value)
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
            future = self._backend.submit(self._backend.bot_runtime.start_bot())
            started = future.result(timeout=10)
        except Exception:
            self._logger.exception("Desktop UI could not start the bot")
            return {"ok": False, "changed": False, "error": "Could not start the bot."}
        return {"ok": True, "changed": started}

    def stop_bot(self) -> dict[str, object]:
        try:
            future = self._backend.submit(self._backend.bot_runtime.stop_bot())
            stopped = future.result(timeout=20)
        except Exception:
            self._logger.exception("Desktop UI could not stop the bot")
            return {"ok": False, "changed": False, "error": "Could not stop the bot."}
        return {"ok": True, "changed": stopped}


def resolve_frontend_url(dev_url: str | None) -> str:
    if dev_url:
        return dev_url
    if not FRONTEND_ENTRYPOINT.is_file():
        raise FileNotFoundError(
            "Frontend build is missing. Run 'npm install' and 'npm run build' in frontend/."
        )
    return str(FRONTEND_ENTRYPOINT)


def apply_twitch_app_settings(settings: Settings, app_settings: AppSettings) -> Settings:
    twitch = app_settings.twitch
    if twitch.channel is None or twitch.channel_user_id is None:
        return settings
    return settings.model_copy(
        update={
            "twitch_channel": twitch.channel,
            "twitch_channel_user_id": twitch.channel_user_id,
        }
    )


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
            if self._tray_started or self._exit_requested:
                return
            self._tray.start()
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
        if self._app_settings.snapshot().window.close_to_tray:
            if self._window is not None:
                self._window.hide()
            return False
        return None

    def _on_closed(self) -> None:
        self._window = None
        self.exit_application()

    def _on_minimized(self) -> None:
        if (
            self._app_settings.snapshot().window.minimize_to_tray
            and self._window is not None
        ):
            self._window.hide()


def run_desktop_host(
    settings: Settings,
    frontend_url: str,
    *,
    auto_start: bool = True,
    credential_manager: CredentialManager | None = None,
) -> None:
    import webview

    app_settings = AppSettingsStore(APP_SETTINGS_PATH)
    settings_snapshot = app_settings.snapshot()
    settings = apply_twitch_app_settings(settings, settings_snapshot)
    backend = AsyncioBackendHost(
        settings,
        auto_start=auto_start,
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
            "Twitch Bot",
            frontend_url,
            js_api=bridge,
            width=1180,
            height=760,
            min_size=(900, 620),
            hidden=settings_snapshot.window.start_minimized,
            background_color="#0b0f17",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("Could not create the desktop window.")
        controller.bind_window(window)
        controller.start_tray()
        development_mode = frontend_url.startswith(("http://", "https://"))
        webview.start(debug=development_mode, http_server=not development_mode)
    finally:
        if controller is not None:
            controller.shutdown()
        else:
            backend.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Twitch bot web desktop UI.")
    parser.add_argument(
        "--dev-url",
        help="Load a running Vite development server instead of built frontend assets.",
    )
    parser.add_argument(
        "--stopped",
        action="store_true",
        help="Open the UI without automatically starting the Twitch bot.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration and locate the requested frontend entry point.",
    )
    arguments = parser.parse_args()
    try:
        settings, credential_manager = load_settings_with_credentials()
        configure_logging(settings.log_level)
        frontend_url = resolve_frontend_url(arguments.dev_url)
        if arguments.check:
            logging.getLogger("app.webview").info("Web desktop configuration check completed")
            return
        run_desktop_host(
            settings,
            frontend_url,
            auto_start=not arguments.stopped,
            credential_manager=credential_manager,
        )
    except (ValidationError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
