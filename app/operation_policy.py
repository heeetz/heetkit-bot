"""Headless operation intent around the shared BotRuntime, on its owning loop."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from time import monotonic

from app.app_settings import AppSettingsStore, OPERATION_MODES
from app.bot_runtime import BotRuntime


logger = logging.getLogger("app.headless.policy")


class OperationPolicy:
    def __init__(self, runtime: BotRuntime, store: AppSettingsStore, *,
                 poll_interval: float = 60.0, max_backoff: float = 900.0,
                 request_timeout: float = 15.0, confirmations: int = 2,
                 clock=monotonic) -> None:
        if (any(not math.isfinite(value) or value <= 0
                for value in (poll_interval, max_backoff, request_timeout))
                or max_backoff < poll_interval or type(confirmations) is not int or confirmations < 2):
            raise ValueError("Invalid internal stream monitoring timing.")
        self.runtime, self.store = runtime, store
        self.mode = store.snapshot().startup.operation_mode
        self.desired_running = self.mode == "always_on"
        self.pending = False
        self.error: str | None = None
        self.stream_status = "unknown"
        self.last_known_stream_status: str | None = None
        self.last_checked_at: str | None = None
        self._poll_interval, self._max_backoff = poll_interval, max_backoff
        self._request_timeout, self._confirmations = request_timeout, confirmations
        self._revision = 0
        self._wake, self._monitor_wake = asyncio.Event(), asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._monitor: asyncio.Task | None = None
        self._closed = False
        self._setup_suspended = False
        self._monitoring = False
        self._clock = clock
        self._stream_checked_at: float | None = None

    def confirmed_stream_status(self) -> str:
        # A failed check immediately invalidates confirmation. A stalled loop or
        # request cannot keep an old observation authoritative indefinitely.
        if (not self._monitoring or self._closed or self._setup_suspended
                or self._stream_checked_at is None
                or self._clock() - self._stream_checked_at >= 2 * self._poll_interval + self._request_timeout):
            return "unknown"
        return self.stream_status

    def refresh_command_monitoring(self) -> None:
        state = self.runtime.application.services.runtime_state
        required = self.mode == "stream_only"
        if not required and self.desired_running and state.server_runtime:
            with state.command_namespace_lock:
                required = any(state.get_command_settings(name).stream_availability != "anytime"
                               for name in state.runtime_toggleable_commands)
                customs = getattr(self.runtime.application, "custom_commands", None)
                required = required or (customs is not None and any(
                    command.stream_availability != "anytime" for command in customs.list()))
        required = bool(required and not self._setup_suspended and not self._closed)
        if required != self._monitoring:
            self._monitoring = required
            self._revision += 1
            self.stream_status = "unknown"
            self._stream_checked_at = None
            self._monitor_wake.set()

    def snapshot(self) -> dict:
        return {"mode": self.mode, "desired_running": self.desired_running,
            "pending": self.pending, "error": self.error,
            "stream_status": self.confirmed_stream_status(),
            "last_known_stream_status": self.last_known_stream_status,
            "last_checked_at": self.last_checked_at}

    def _schedule(self) -> None:
        self.refresh_command_monitoring()
        self.pending = True
        if not self.desired_running and self.runtime.bot_active:
            # Intent is visible before close yields or supervision sees completion.
            self.runtime.request_stop()
        self._wake.set()

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("Operation policy has closed.")
        if self._worker is not None:
            return
        self.runtime.application.services.runtime_state.server_stream_status = self.confirmed_stream_status
        self._worker = asyncio.create_task(self._reconcile(), name="heetkit-operation-policy")
        self._monitor = asyncio.create_task(self._monitor_stream(), name="heetkit-stream-monitor")
        self._schedule()

    def set_mode(self, mode: object) -> bool:
        if self._closed or not isinstance(mode, str) or mode not in OPERATION_MODES:
            raise ValueError("Unknown or unavailable operation mode.")
        if mode == self.mode:
            return False
        # Save before publishing intent. Failed writes cannot partially change policy.
        self.store.update_operation_mode(mode)
        self._revision += 1
        self.mode = mode
        self.error = None
        self.stream_status = "unknown"
        self.desired_running = (mode == "always_on" or
            (mode == "stream_only" and self.desired_running and self.runtime.bot_active))
        self._monitor_wake.set()
        self._schedule()
        logger.info("Operation mode changed: %s", mode, extra={"event_kind": "operation.mode"})
        return True

    def connect(self) -> bool:
        if self._closed or self.mode != "manual":
            raise ValueError("Choose Manual before connecting explicitly.")
        changed = not self.desired_running or self.error is not None
        self.error = None
        self.desired_running = True
        self._schedule()
        return changed

    def disconnect(self) -> bool:
        if self._closed:
            raise ValueError("Operation policy has closed.")
        if self.mode in {"always_on", "stream_only"}:
            return self.set_mode("manual")
        changed = self.desired_running
        self.desired_running = False
        self._schedule()
        return changed

    def connection_failed(self) -> None:
        if self.error is None:
            self.error = "connection_failed"
            # Keep the saved policy and management alive, but do not race TwitchIO
            # with another retry loop or repeat a terminal auth/storage failure.
            self.desired_running = False
            self._schedule()
            logger.error("Twitch connection needs administrator attention.",
                extra={"event_kind": "operation.failed"})

    async def suspend_for_setup(self) -> None:
        """Quiesce sessions and discard in-flight polls without changing saved mode."""
        self._setup_suspended = True
        self._revision += 1
        self.desired_running = False
        self._monitor_wake.set()
        self._schedule()
        # A terminal session may already have reported its failure. Discard that
        # completed task so administrators can repair credentials/re-authorize;
        # errors from an active close/token flush still abort this operation.
        await self.runtime.stop_bot(recover_failed=True)
        twitch = getattr(self.runtime.application.services, "twitch", None)
        if twitch is not None:
            await twitch.close_stream_monitor()

    def resume_after_setup(self) -> None:
        self._setup_suspended = False
        self._revision += 1
        self.error = None
        self.stream_status = "unknown"
        self.desired_running = self.mode == "always_on"
        self._monitor_wake.set()
        self._schedule()

    async def _reconcile(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            try:
                if self.desired_running and self.error is None and not self._setup_suspended:
                    await self.runtime.start_bot()
                else:
                    await self.runtime.stop_bot()
            except Exception:
                self.connection_failed()
            finally:
                self.pending = self._wake.is_set()

    async def _monitor_stream(self) -> None:
        candidate: bool | None = None
        count = failures = 0
        revision = self._revision
        while True:
            self._monitor_wake.clear()
            if not self._monitoring:
                await self._monitor_wake.wait()
                continue
            if revision != self._revision:
                candidate, count, failures = None, 0, 0
                revision = self._revision
            try:
                async with asyncio.timeout(self._request_timeout):
                    live = await self.runtime.application.services.twitch.get_broadcaster_live(
                        self.runtime.application.settings)
                if type(live) is not bool:
                    raise ValueError("Unknown live status")
            except Exception:
                live = None
                # Failed login/expired app tokens are retried through TwitchIO on
                # the next bounded poll; never touch the bot's user-token cache.
                try:
                    await self.runtime.application.services.twitch.close_stream_monitor()
                except Exception:
                    logger.warning("Stream API cleanup failed.", extra={"event_kind": "operation.poll"})
            if revision != self._revision or not self._monitoring:
                continue  # Discard a response from a superseded policy.
            self.last_checked_at = datetime.now(timezone.utc).isoformat()
            self._stream_checked_at = self._clock() if live is not None else None
            previous = self.stream_status
            self.stream_status = "unknown" if live is None else "live" if live else "offline"
            if live is None:
                candidate, count = None, 0
                failures = min(failures + 1, 10)
            else:
                failures = 0
                self.last_known_stream_status = self.stream_status
                count = count + 1 if candidate is live else 1
                candidate = live
                if (self.mode == "stream_only" and count >= self._confirmations
                        and self.error is None and self.desired_running != live):
                    self.desired_running = live
                    self._schedule()
                    logger.info("Confirmed stream transition: %s", self.stream_status,
                        extra={"event_kind": "operation.stream"})
            if previous != self.stream_status or live is None:
                logger.info("Stream check: %s", self.stream_status,
                    extra={"event_kind": "operation.poll"})
            delay = min(self._max_backoff, self._poll_interval * 2 ** failures)
            try:
                await asyncio.wait_for(self._monitor_wake.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.desired_running = False
        self.runtime.request_stop()
        tasks = [task for task in (self._monitor, self._worker) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        twitch = getattr(self.runtime.application.services, "twitch", None)
        if twitch is not None:
            await twitch.close_stream_monitor()
        self.pending = False
