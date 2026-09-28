"""pywebview desktop host for the React presentation layer."""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Coroutine

from pydantic import ValidationError

from app.bot_runtime import BotRuntime
from app.config.settings import Settings, load_settings
from app.container import Application, build_application
from app.utils.logging import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ENTRYPOINT = PROJECT_ROOT / "frontend" / "dist" / "index.html"


class AsyncioBackendHost:
    """Own the application and its single asyncio loop on a background thread."""

    def __init__(self, settings: Settings, *, auto_start: bool = True) -> None:
        self._settings = settings
        self._auto_start = auto_start
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

    def __init__(self, backend: AsyncioBackendHost) -> None:
        self._backend = backend
        self._logger = get_logger("app.webview.bridge")

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
                }
            )
        return {
            "command_prefix": application.settings.command_prefix,
            "commands": commands,
        }

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


def run_desktop_host(settings: Settings, frontend_url: str, *, auto_start: bool = True) -> None:
    import webview

    backend = AsyncioBackendHost(settings, auto_start=auto_start)
    try:
        backend.start()
        webview.create_window(
            "Twitch Bot",
            frontend_url,
            js_api=WebUIBridge(backend),
            width=1180,
            height=760,
            min_size=(900, 620),
            background_color="#0b0f17",
            text_select=True,
        )
        development_mode = frontend_url.startswith(("http://", "https://"))
        webview.start(debug=development_mode, http_server=not development_mode)
    finally:
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
        settings = load_settings()
        configure_logging(settings.log_level)
        frontend_url = resolve_frontend_url(arguments.dev_url)
        if arguments.check:
            logging.getLogger("app.webview").info("Web desktop configuration check completed")
            return
        run_desktop_host(settings, frontend_url, auto_start=not arguments.stopped)
    except (ValidationError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
