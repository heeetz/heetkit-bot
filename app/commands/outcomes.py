"""Transient invocation outcomes, shared by handlers and awaited chat sends.

Nothing in this context is persisted: only the single terminal classification is
published. A normal handler return is deliberately not a completion signal.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.utils.logging import operator_event


@dataclass
class InvocationOutcome:
    message: object
    command_id: str
    started: bool = False
    completed: bool = False
    skip: str | None = None
    error: str | None = None
    planned: int = 0
    attempted: int = 0
    confirmed: int = 0
    failed: int = 0
    uncertain: int = 0
    closed: bool = False

    def terminal(self):
        pending = max(0, self.attempted - self.confirmed - self.failed - self.uncertain)
        if self.skip is not None and not self.started:
            return "skipped", self.skip
        if self.confirmed and (self.failed or self.uncertain or self.confirmed < self.planned):
            return "partial", "uncertain_delivery" if self.uncertain or pending else self.error or "incomplete_delivery"
        if self.uncertain or pending:
            return "uncertain", "uncertain_delivery"
        if self.error or self.failed:
            return "error", self.error or "delivery_failed"
        if self.skip is not None:
            return "skipped", self.skip
        if self.planned and self.confirmed == self.planned:
            return "success", "confirmed_delivery"
        if self.completed and not self.planned:
            return "success", "completed"
        return "incomplete", "no_completed_outcome"


_current: ContextVar[InvocationOutcome | None] = ContextVar("command_outcome", default=None)


def current_outcome():
    state = _current.get()
    return state if state is not None and not state.closed else None


def skip_outcome(reason):
    if (state := current_outcome()) is not None:
        state.skip = reason


def fail_outcome(reason):
    if (state := current_outcome()) is not None:
        state.error = reason


def complete_outcome():
    if (state := current_outcome()) is not None:
        state.completed = True


def start_outcome(logger):
    if (state := current_outcome()) is not None and not state.started:
        state.started = True
        operator_event(logger, "command.start", "executing", command_id=state.command_id)


def plan_sends(count):
    if (state := current_outcome()) is not None:
        state.planned += count


def send_started():
    if (state := current_outcome()) is not None:
        state.attempted += 1


def send_finished(outcome):
    if (state := current_outcome()) is not None:
        if outcome == "confirmed_send":
            state.confirmed += 1
        elif outcome == "failed_send":
            state.failed += 1
        else:
            state.uncertain += 1


@contextmanager
def invocation_scope(message, command_id, logger):
    current = current_outcome()
    if not command_id or (current is not None and current.message is message):
        yield
        return
    state = InvocationOutcome(message, command_id)
    token = _current.set(state)
    try:
        operator_event(logger, "command.attempt", "known", command_id=command_id)
        yield
    except BaseException:
        state.error = state.error or "cancelled_or_interrupted"
        raise
    finally:
        outcome, reason = state.terminal()
        state.closed = True
        operator_event(logger, "command.terminal", outcome, command_id=command_id, reason=reason)
        _current.reset(token)
