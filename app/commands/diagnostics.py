"""Opt-in command timing and outcomes without chat text or account identifiers."""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic, time
from uuid import UUID, uuid4


LOGGER = logging.getLogger("app.command_diagnostics")
EVENT_KIND = "command.trace"
OBSERVED_EVENTS = frozenset({"command.attempt", "command.start", "command.terminal", "command.outcome",
                             "ai.result", "chat.filtered", "chat.send", "chat.outgoing"})
COMMANDS = frozenset({"ask", "weather"})
OUTCOMES = frozenset({"skipped", "success", "error", "uncertain", "partial", "incomplete", "cancelled"})
REASONS = frozenset({
    "ai_unavailable", "ai_user_blocked", "availability", "cancelled", "cancelled_or_interrupted",
    "city_not_found", "completed", "confirmed_delivery", "cooldown", "delivery_failed", "disabled",
    "filters", "followage_unavailable", "handler_failed", "incomplete_delivery", "invalid_arguments",
    "no_completed_outcome", "no_data", "no_retained_user", "outgoing_envelope", "output_limiter",
    "permissions", "presence_unavailable", "provider_failure", "restricted", "uncertain_delivery",
    "unknown_command", "weather_empty_query", "weather_in_flight", "weather_invalid_query",
    "weather_invalid_response", "weather_output_blocked", "weather_output_filter_timeout",
    "weather_provider_failure", "weather_qualifier_mismatch", "weather_rate_limited",
    "weather_send_failed", "weather_send_session_closed", "weather_timeout",
})
AI_STATUSES = frozenset({
    "success", "output_blocked", "provider_unavailable", "api_error", "timeout", "model_unavailable",
    "configuration_error", "search_error", "search_unavailable", "attribution_unavailable",
    "question_too_long", "outgoing_envelope",
})
SEND_OUTCOMES = {
    "confirmed_send": "confirmed", "failed_send": "rejected", "uncertain_send": "uncertain",
    "limiter_skip": "limited",
}


def receipt_time():
    return time(), monotonic()


def _trace_id(message_id: str | None) -> str:
    if isinstance(message_id, str) and len(message_id) == 36:
        try:
            stable_id = UUID(message_id)
        except ValueError:
            pass
        else:
            return hashlib.sha256(stable_id.bytes).hexdigest()[:24]
    return uuid4().hex[:24]


@dataclass(slots=True)
class CommandTrace:
    trace_id: str
    command: str
    received_utc: str
    started_at: float
    suppressed: Callable[[], bool]
    db_wait_ms: float | None = None
    db_failed: bool = False
    dispatch_ms: float | None = None
    handler_ms: float | None = None
    outcome: str = "incomplete"
    reason: str = "no_terminal_outcome"
    input_block: str | None = None
    ai_status: str | None = None
    cancelled: bool = False
    send_session_closed: bool = False
    sends: dict[str, int] = field(default_factory=dict)
    closed: bool = False

    def elapsed_ms(self) -> float:
        return round((monotonic() - self.started_at) * 1000, 3)

    def emit(self, phase: str) -> None:
        if self.suppressed():
            return
        data = {"id": self.trace_id, "phase": phase, "command": self.command,
                "received_utc": self.received_utc}
        if phase == "terminal":
            data.update(db_wait_ms=self.db_wait_ms, db_failed=self.db_failed,
                        dispatch_ms=self.dispatch_ms, handler_ms=self.handler_ms,
                        elapsed_ms=self.elapsed_ms(), outcome=self.outcome, reason=self.reason,
                        input_block=self.input_block, ai_status=self.ai_status, cancelled=self.cancelled,
                        send_session_closed=self.send_session_closed, sends=self.sends)
        LOGGER.info("Command trace %s", json.dumps(data, separators=(",", ":")), extra={"event_kind": EVENT_KIND})


_active: ContextVar[CommandTrace | None] = ContextVar("command_trace", default=None)


def current_trace() -> CommandTrace | None:
    trace = _active.get()
    return trace if trace is not None and not trace.closed else None


@contextmanager
def command_trace(receipt, command: str, message_id: str | None, suppressed: Callable[[], bool]):
    if receipt is None or suppressed():
        yield
        return
    wall, started_at = receipt
    trace = CommandTrace(_trace_id(message_id), command if command in COMMANDS else "other",
                         datetime.fromtimestamp(wall, timezone.utc).isoformat(), started_at, suppressed)
    token = _active.set(trace)
    try:
        trace.emit("received")
        yield
    except asyncio.CancelledError:
        trace.cancelled = True
        if trace.outcome not in {"partial", "uncertain", "success"}:
            trace.outcome, trace.reason = "cancelled", "cancelled"
        raise
    except Exception:
        trace.outcome, trace.reason = "error", "handler_failed"
        raise
    finally:
        trace.closed = True
        _active.reset(token)
        trace.emit("terminal")


def presence_lock_timer() -> Callable[[], None] | None:
    trace = current_trace()
    if trace is None:
        return None
    queued_at = monotonic()

    def acquired() -> None:
        trace.db_wait_ms = round((monotonic() - queued_at) * 1000, 3)

    return acquired


def observe_command_event(kind: str, values: dict) -> None:
    trace = current_trace()
    if trace is None:
        return
    if kind == "command.attempt":
        command = values.get("command_id")
        if command in COMMANDS:
            trace.command = command
    elif kind == "command.start":
        trace.handler_ms = trace.elapsed_ms()
    elif kind == "command.terminal":
        outcome, reason = values.get("outcome"), values.get("reason")
        trace.outcome = outcome if outcome in OUTCOMES else "incomplete"
        trace.reason = reason if reason in REASONS else "other_outcome"
    elif kind == "command.outcome":
        if values.get("outcome") == "unknown_command":
            trace.outcome, trace.reason = "skipped", "unknown_command"
        elif values.get("reason") == "protected_policy":
            trace.input_block = "protected_policy"
    elif kind == "chat.filtered":
        trace.input_block = "content_filter"
    elif kind == "ai.result":
        status = values.get("reason")
        trace.ai_status = status if status in AI_STATUSES else "other_status"
    elif kind in {"chat.send", "chat.outgoing"}:
        result = "attempted" if kind == "chat.send" else SEND_OUTCOMES.get(values.get("outcome"))
        if result:
            trace.sends[result] = trace.sends.get(result, 0) + 1
