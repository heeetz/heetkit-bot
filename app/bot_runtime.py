"""Reusable Twitch bot lifecycle owned by one asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from app.container import Application
from app.twitch.client import run_twitch_bot


class BotRuntime:
    """Start and stop one composed application without duplicating its state."""

    def __init__(self, application: Application, logger: logging.Logger) -> None:
        self.application = application
        self._logger = logger
        self._lifecycle_lock = asyncio.Lock()
        self._stop_event: asyncio.Event | None = None
        self._bot_task: asyncio.Task[None] | None = None
        self._startup_attempted = False
        self._started = False
        self._stop_requested = False
        self._shutdown = False

    async def startup(self) -> None:
        if self._started:
            return
        if self._shutdown:
            raise RuntimeError("Application has already shut down.")
        self._startup_attempted = True
        await self.application.startup()
        self._started = True

    async def start_bot(self) -> bool:
        """Start the Twitch session and return whether a new session was created."""
        async with self._lifecycle_lock:
            if not self._started:
                raise RuntimeError("Application startup has not completed.")
            if self._bot_task is not None and not self._bot_task.done():
                return False
            if self._bot_task is not None:
                with suppress(Exception):
                    self._bot_task.result()
            if self._bot_task is None and self._stop_requested:
                self._stop_requested = False
                return False

            self._stop_requested = False
            self._stop_event = asyncio.Event()
            self.application.services.runtime_state.set_bot_running(True)
            self._bot_task = asyncio.create_task(
                self._run_bot_session(self._stop_event),
                name="twitch-bot-session",
            )
            return True

    async def _run_bot_session(self, stop_event: asyncio.Event) -> None:
        try:
            await run_twitch_bot(
                settings=self.application.settings,
                services=self.application.services,
                dispatcher=self.application.dispatcher,
                logger=self._logger,
                stop_event=stop_event,
            )
        finally:
            self.application.services.runtime_state.set_bot_running(False)

    def request_stop(self) -> None:
        """Signal the current Twitch session from its owning event loop."""
        self._stop_requested = True
        if self._stop_event is not None:
            self._stop_event.set()

    async def stop_bot(self) -> bool:
        """Stop the Twitch session, suppressing an already reported session failure."""
        async with self._lifecycle_lock:
            task = self._bot_task
            if task is None or task.done():
                if task is not None:
                    with suppress(Exception):
                        task.result()
                self.application.services.runtime_state.set_bot_running(False)
                return False
            self.request_stop()

        with suppress(Exception):
            await task
        return True

    async def wait_until_stopped(self) -> None:
        task = self._bot_task
        if task is not None:
            await task

    async def shutdown(self) -> None:
        if self._shutdown:
            return
        if self._started:
            await self.stop_bot()
        if self._startup_attempted:
            await self.application.shutdown()
        self._started = False
        self._shutdown = True
