"""Shared chat output and connection-scoped ownership on the backend loop."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from uuid import uuid4

from app.command_settings import validate_burst_interval, validate_burst_max_count
from app.twitch.message_correlation import send_error_outcome
from app.utils.logging import operator_event, operator_event_scope, send_outcome
from app.utils.output_limiter import OutputLimiter


class ChatSessionClosedError(RuntimeError):
    """The connection captured by this sender is no longer available."""


class ChatSendSession:
    """Own in-flight sends and Burst timers until this connection is invalidated."""

    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.tasks: set[asyncio.Task] = set()

    def invalidate(self) -> None:
        if not self.active:
            return
        self.active = False
        for task in tuple(self.tasks):
            task.cancel()

    async def run(self, operation: Callable[[], Awaitable]):
        if not self.active:
            raise ChatSessionClosedError("Twitch chat connection is no longer available.")

        async def execute():
            if not self.active:
                raise ChatSessionClosedError("Twitch chat connection is no longer available.")
            return await operation()

        task = asyncio.create_task(execute())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return await task


class ChatSender:
    """Apply the same limits, delivery results and diagnostics for every source."""

    def __init__(
        self,
        responder: Callable[[str], Awaitable[object]],
        logger: logging.Logger,
        output_limiter: OutputLimiter | None = None,
        session: ChatSendSession | None = None,
        context: dict | None = None,
    ) -> None:
        self._responder = responder
        self._logger = logger
        self._output_limiter = output_limiter
        self._session = session
        self._context = context

    async def _run(self, operation: Callable[[], Awaitable]):
        with operator_event_scope(**self._context) if self._context is not None else nullcontext():
            if self._session is None:
                return await operation()
            return await self._session.run(operation)

    async def reply(self, content: str) -> bool:
        async def send() -> bool:
            if self._output_limiter is not None and not self._output_limiter.try_acquire():
                operator_event(self._logger, "chat.outgoing", "limiter_skip", response_id=uuid4().hex)
                return False
            result = await self._send_response(content)
            return send_outcome(result) == "confirmed_send"

        return await self._run(send)

    async def _send_response(self, content: str) -> object:
        with operator_event_scope(response_id=uuid4().hex):
            operator_event(self._logger, "chat.send", "attempt")
            try:
                result = await self._responder(content)
            except BaseException as error:
                operator_event(self._logger, "chat.outgoing", send_error_outcome(error), text=content)
                raise
            message_id = getattr(result, "id", None)
            operator_event(self._logger, "chat.outgoing", send_outcome(result),
                           message_id=message_id if isinstance(message_id, str) else None, text=content)
            return result

    async def reply_burst(self, content: str, count: int, interval_ms: int, maximum: int) -> list[object]:
        maximum = validate_burst_max_count(maximum)
        if type(count) is not int or not 1 <= count <= maximum:
            raise ValueError(f"Burst repeat count must be an integer from 1 to {maximum}.")
        interval = validate_burst_interval(interval_ms)

        async def batch() -> list[object]:
            async def send(index: int) -> object:
                if index and interval:
                    await asyncio.sleep(index * interval / 1000)
                return await self._send_response(content)

            return await asyncio.gather(*(send(index) for index in range(count)), return_exceptions=True)

        return await self._run(batch)
