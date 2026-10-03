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
            return self._start_bot_locked()

    def _start_bot_locked(self) -> bool:
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

        self.application.settings.validate_twitch_configuration()
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
            if stop_event.is_set():
                self.application.services.runtime_state.set_twitch_connection_state("stopped")

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

    async def reconnect_twitch(
        self,
        *,
        channel: str,
        channel_user_id: str,
    ) -> bool:
        """Apply target-channel settings and reconnect an active Twitch session."""
        async with self._lifecycle_lock:
            if not self._started:
                raise RuntimeError("Application startup has not completed.")
            task = self._bot_task
            was_running = task is not None and not task.done()
            if was_running:
                self.application.settings.model_copy(update={
                    "twitch_channel": channel, "twitch_channel_user_id": channel_user_id,
                }).validate_twitch_configuration()
            if was_running:
                self.request_stop()
                with suppress(Exception):
                    await task
            self.application.settings.twitch_channel = channel
            self.application.settings.twitch_channel_user_id = channel_user_id
            if was_running:
                self._start_bot_locked()
            return was_running

    async def shutdown(self) -> None:
        if self._shutdown:
            return
        if self._started:
            await self.stop_bot()
        if self._startup_attempted:
            await self.application.shutdown()
        self._started = False
        self._shutdown = True
