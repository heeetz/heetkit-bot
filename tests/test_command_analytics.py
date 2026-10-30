"""Logical command outcomes use explicit work/delivery rather than normal return."""

import asyncio
import logging
from types import SimpleNamespace as NS

import pytest
from twitchio.exceptions import HTTPException

from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownManager, CooldownPolicy
from app.utils.output_limiter import OutputLimiter


def dispatcher(registry, **kwargs):
    return CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!", **kwargs)


def message(content, responder=None, **roles):
    async def confirmed(_):
        return NS(sent=True)
    return IncomingChatMessage("synthetic", content, ChatAuthor("123", "viewer", **roles),
                               responder or confirmed, channel_id="456")


def events(caplog, kind):
    return [record for record in caplog.records if getattr(record, "event_kind", None) == kind]


@pytest.mark.asyncio
async def test_known_attempts_aliases_and_early_ingress_scope_are_one_logical_attempt(caplog):
    registry = CommandRegistry()
    @registry.command("ping", aliases=("p",))
    async def ping(context, _):
        await context.reply("pong")
    dispatch = dispatcher(registry)
    with caplog.at_level(logging.INFO):
        assert not await dispatch.dispatch(message("!elo otherbot"), NS())
        incoming = message("!p")
        with dispatch.event_scope(incoming), dispatch.outcome_scope(incoming):
            await dispatch.dispatch(incoming, NS())
    assert len(events(caplog, "command.attempt")) == 1
    assert events(caplog, "command.attempt")[0].event_command_id == "ping"
    assert len(events(caplog, "command.start")) == 1
    terminal, = events(caplog, "command.terminal")
    assert terminal.event_outcome == "success"
    assert terminal.event_reason == "confirmed_delivery"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("return", "incomplete"), ("complete", "success"),
                                         ("raise", "error"), ("uncertain", "uncertain"),
                                         ("failed", "error")])
async def test_normal_return_is_not_success_and_delivery_is_explicit(caplog, mode, expected):
    registry = CommandRegistry()
    @registry.command("work")
    async def work(context, _):
        if mode == "complete":
            context.complete()
        elif mode == "raise":
            raise ValueError("PRIVATE input")
        elif mode in {"uncertain", "failed"}:
            await context.reply("answer")
    async def respond(_):
        return NS(sent=False) if mode == "failed" else None
    with caplog.at_level(logging.INFO):
        await dispatcher(registry).dispatch(message("!work", respond), NS())
    terminal, = events(caplog, "command.terminal")
    assert terminal.event_outcome == expected
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["permission", "disabled", "precheck", "cooldown", "restriction", "limiter"])
async def test_precheck_denials_never_become_execution_errors(caplog, mode):
    registry = CommandRegistry()
    @registry.command("work", enabled_by_default=mode != "disabled",
                      required_permission=Permission.MODERATOR if mode == "permission" else Permission.USER,
                      pre_check=(lambda context, args: False) if mode == "precheck" else None,
                      cooldown=CooldownPolicy(global_seconds=60 if mode == "cooldown" else 0))
    async def work(context, _):
        await context.reply("answer")
    limiter = OutputLimiter(interval=60) if mode == "limiter" else None
    if limiter:
        limiter.try_acquire()
    dispatch = dispatcher(registry, output_limiter=limiter)
    services = NS(command_restrictions=NS(match=lambda *args: NS(expires_at=None)) if mode == "restriction" else None)
    if mode == "cooldown":
        await dispatch.dispatch(message("!work"), services)
    with caplog.at_level(logging.INFO):
        await dispatch.dispatch(message("!work"), services)
    terminal, = events(caplog, "command.terminal")
    assert terminal.event_outcome == "skipped"
    assert len(events(caplog, "command.start")) == (1 if mode == "limiter" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("results,expected,reason", [
    ([True, True, True], "success", "confirmed_delivery"),
    ([True, False, False], "partial", "incomplete_delivery"),
    ([True, None, True], "partial", "uncertain_delivery"),
    ([None, None, None], "uncertain", "uncertain_delivery"),
    ([False, False, False], "error", "delivery_failed"),
])
async def test_burst_has_one_start_and_one_mutually_exclusive_terminal(caplog, results, expected, reason):
    registry = CommandRegistry()
    @registry.command("burst")
    async def burst(context, _):
        await context.reply_burst("answer", len(results))
    remaining = iter(results)
    async def respond(_):
        result = next(remaining)
        if result is False:
            raise HTTPException("synthetic", status=429, extra={})
        return None if result is None else NS(sent=True)
    with caplog.at_level(logging.INFO):
        await dispatcher(registry).dispatch(message("!burst", respond), NS())
    assert len(events(caplog, "command.attempt")) == len(events(caplog, "command.start")) == 1
    terminal, = events(caplog, "command.terminal")
    assert (terminal.event_outcome, terminal.event_reason) == (expected, reason)


@pytest.mark.asyncio
async def test_custom_alias_uses_saved_id_across_rename(tmp_path, caplog):
    registry = CommandRegistry()
    store = CustomCommandStore(tmp_path / "custom.json", set())
    payload = {"enabled": True, "permission": "USER", "per_user_seconds": 0, "global_seconds": 0,
               "responses": ["Hi"]}
    first = store.save({**payload, "name": "greeting", "aliases": ["hello"]})
    dispatch = dispatcher(registry, custom_commands=store)
    with caplog.at_level(logging.INFO):
        await dispatch.dispatch(message("!hello"), NS())
        store.save({**payload, "id": first.id, "name": "welcome", "aliases": []})
        await dispatch.dispatch(message("!welcome"), NS())
    assert [r.event_command_id for r in events(caplog, "command.attempt")] == [f"custom:{first.id}"] * 2


@pytest.mark.asyncio
async def test_limiter_after_confirmed_response_is_partial_not_precheck_skip(caplog):
    registry = CommandRegistry()
    @registry.command("work")
    async def work(context, _):
        await context.reply("first")
        await context.reply("second")
    with caplog.at_level(logging.INFO):
        await dispatcher(registry, output_limiter=OutputLimiter(interval=60)).dispatch(message("!work"), NS())
    terminal, = events(caplog, "command.terminal")
    assert terminal.event_outcome == "partial"


@pytest.mark.asyncio
async def test_cancelled_burst_drains_children_and_reports_partial_once(caplog):
    registry = CommandRegistry()
    waiting = asyncio.Event()
    @registry.command("burst")
    async def burst(context, _):
        await context.reply_burst("answer", 2)
    calls = 0
    async def respond(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return NS(sent=True)
        waiting.set()
        await asyncio.Event().wait()
    with caplog.at_level(logging.INFO):
        task = asyncio.create_task(dispatcher(registry).dispatch(message("!burst", respond), NS()))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    terminal, = events(caplog, "command.terminal")
    assert terminal.event_outcome == "partial"
    assert terminal.event_reason == "uncertain_delivery"
