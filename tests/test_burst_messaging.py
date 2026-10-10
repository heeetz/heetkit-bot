"""Bursts share one bounded, awaited transport path without app output throttling."""

import asyncio
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from twitchio.exceptions import HTTPException, MessageRejectedError
from twitchio.models import SentMessage

from app.commands.fun import register_fun_commands
from app.commands.registry import CommandContext, CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.fun_settings import FunSettingsStore
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownManager
from app.utils.output_limiter import OutputLimiter


def burst_payload(**changes):
    return {
        "name": "promo", "enabled": True, "responses": ["Join our community, {sender}!"],
        "permission": "MODERATOR", "per_user_seconds": 0, "global_seconds": 0,
        "aliases": ["promotion"], "response_mode": "burst", "burst_count": 5,
        "burst_allow_override": False, **changes,
    }


def setup_dispatcher(tmp_path, **changes):
    registry = CommandRegistry()
    fun = FunSettingsStore(tmp_path / "fun.json")
    register_fun_commands(registry, fun)
    store = CustomCommandStore(tmp_path / "commands.json", set(registry.names()))
    store.save(burst_payload(**changes))
    limiter = OutputLimiter(interval=60)
    dispatcher = CommandDispatcher(
        registry, CooldownManager(), logging.getLogger(__name__), "!",
        output_limiter=limiter, custom_commands=store,
    )
    users = SimpleNamespace(recent_usernames=AsyncMock(return_value=["alice", "bob"]))
    services = SimpleNamespace(users=users, settings=SimpleNamespace(
        twitch_bot_user_id="bot", twitch_bot_username="bot"))
    return dispatcher, store, limiter, services


def message(content, responder, **roles):
    return IncomingChatMessage("channel", content, ChatAuthor("user", "caller", **roles), responder)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["tg", "promo"])
@pytest.mark.parametrize("count", range(1, 11))
async def test_all_sends_start_before_any_response_finishes(tmp_path, command, count):
    dispatcher, _, limiter, services = setup_dispatcher(tmp_path, burst_count=count)
    assert limiter.try_acquire()  # Even an already occupied limiter cannot trim a burst.
    started = []
    finished = []
    all_started = asyncio.Event()
    release = asyncio.Event()

    async def respond(content):
        started.append(content)
        if len(started) == count:
            all_started.set()
        await release.wait()
        finished.append(content)

    invocation = f"!tg {count}" if command == "tg" else "!promotion"
    task = asyncio.create_task(dispatcher.dispatch(message(invocation, respond, is_moderator=True), services))
    try:
        await asyncio.wait_for(all_started.wait(), 2)
        assert len(started) == count
        assert finished == []
        assert not task.done()
        release.set()
        assert await task
        assert len(finished) == count
        assert not limiter.try_acquire()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_batch_collects_success_drops_http_limits_rejections_and_child_cancellation(caplog):
    sent = SentMessage({"message_id": "sent", "is_sent": True})
    dropped = SentMessage({"message_id": "", "is_sent": False,
                           "drop_reason": {"code": "rate_limit_exceeded", "message": "Limited"}})
    rate_limit = HTTPException("Rate limited", status=429, extra={"message": "Limited"})
    rejected = MessageRejectedError("Rejected", message=dropped, channel=None, content="Hello")
    failure = RuntimeError("Synthetic failure")
    outcomes = iter([sent, rate_limit, rejected, dropped, failure, asyncio.CancelledError()])
    starts = []

    async def respond(content):
        starts.append(content)
        outcome = next(outcomes)
        await asyncio.sleep(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    context = CommandContext(message("!promo", respond), SimpleNamespace(), logging.getLogger(__name__))
    results = await context.reply_burst("Hello", 6)
    assert starts == ["Hello"] * 6
    assert results[:5] == [sent, rate_limit, rejected, dropped, failure]
    assert isinstance(results[5], asyncio.CancelledError)
    assert rate_limit.status == 429
    assert "Twitch dropped command response" in caplog.text
    assert "Could not send command response" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["tg", "promo"])
async def test_cancelling_invocation_drains_all_transport_cleanup(tmp_path, command):
    dispatcher, _, _, services = setup_dispatcher(tmp_path)
    started = asyncio.Event()
    cleanup_started = []
    cleaned = []
    release_cleanup = asyncio.Event()
    all_cleaning = asyncio.Event()
    calls = 0

    async def respond(content):
        nonlocal calls
        calls += 1
        if calls == 5:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.append(content)
            if len(cleanup_started) == 5:
                all_cleaning.set()
            await release_cleanup.wait()
            cleaned.append(content)

    invocation = "!tg 5" if command == "tg" else "!promo"
    task = asyncio.create_task(dispatcher.dispatch(message(invocation, respond, is_moderator=True), services))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.wait_for(all_cleaning.wait(), 2)
        assert not task.done()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == len(cleaned) == 5
    finally:
        release_cleanup.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_both_commands_call_the_same_burst_helper(tmp_path, monkeypatch):
    dispatcher, _, _, services = setup_dispatcher(tmp_path)
    shared = AsyncMock(return_value=[])
    monkeypatch.setattr(CommandContext, "reply_burst", shared)
    respond = AsyncMock()
    await dispatcher.dispatch(message("!tg 3", respond, is_moderator=True), services)
    await dispatcher.dispatch(message("!promo", respond, is_moderator=True), services)
    assert [call.args[1] for call in shared.await_args_list] == [3, 5]
    respond.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1, 11, True, 1.5, "2", None])
async def test_helper_rejects_invalid_counts_before_any_send(count):
    respond = AsyncMock()
    context = CommandContext(message("!promo", respond), SimpleNamespace(), logging.getLogger(__name__))
    with pytest.raises(ValueError, match="1 to 10"):
        await context.reply_burst("Hello", count)
    respond.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("roles,allowed", [({}, False), ({"is_subscriber": True}, False),
    ({"is_vip": True}, False), ({"is_moderator": True}, True), ({"is_broadcaster": True}, True)])
async def test_burst_permission_floor_even_for_an_invalid_runtime_snapshot(tmp_path, roles, allowed):
    dispatcher, store, _, services = setup_dispatcher(tmp_path)
    command = store.list()[0]
    # Defense in depth: even a faulty store adapter cannot lower Burst to viewer.
    store._publish({command.id: replace(command, permission=Permission.USER)})
    respond = AsyncMock()
    assert await dispatcher.dispatch(message("!promotion", respond, **roles), services)
    assert respond.await_count == (5 if allowed else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ["0", "11", "-1", "2.5", "many", "10 extra " * 40])
async def test_invalid_override_sends_no_partial_batch(tmp_path, arguments):
    dispatcher, _, _, services = setup_dispatcher(tmp_path, burst_allow_override=True)
    respond = AsyncMock()
    assert await dispatcher.dispatch(message(f"!promo {arguments}", respond, is_moderator=True), services)
    respond.assert_not_awaited()
    services.users.recent_usernames.assert_not_awaited()


@pytest.mark.asyncio
async def test_burst_renders_once_and_override_is_removed_from_template_arguments(tmp_path):
    template = "{sender}|{target}|{args}|{arg1}|{arg2}|{random_user}"
    dispatcher, _, _, services = setup_dispatcher(
        tmp_path, responses=[template], burst_allow_override=True,
    )
    respond = AsyncMock()
    await dispatcher.dispatch(message("!promo", respond, is_moderator=True), services)
    assert respond.await_count == 5
    default = respond.await_args_list[0].args[0]
    assert default.startswith("caller|caller||||")
    assert all(call.args == (default,) for call in respond.await_args_list)
    services.users.recent_usernames.assert_awaited_once()
    respond.reset_mock()
    services.users.recent_usernames.reset_mock()
    await dispatcher.dispatch(message("!promo 10 @target second", respond, is_moderator=True), services)
    assert respond.await_count == 10
    rendered = respond.await_args_list[0].args[0]
    assert rendered.startswith("caller|target|@target second|@target|second|")
    assert all(call.args == (rendered,) for call in respond.await_args_list)
    services.users.recent_usernames.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_override_keeps_arguments_and_applies_existing_length_limit(tmp_path):
    dispatcher, _, _, services = setup_dispatcher(tmp_path, responses=["{args}" + "😀" * 300], burst_count=3)
    respond = AsyncMock()
    await dispatcher.dispatch(message("!promo 10", respond, is_moderator=True), services)
    assert respond.await_count == 3
    assert all(call.args[0].startswith("10") and len(call.args[0].encode("utf-8")) <= 450
               for call in respond.await_args_list)


@pytest.mark.asyncio
async def test_single_random_and_burst_share_cooldowns_but_only_burst_bypasses_output_limit(tmp_path):
    dispatcher, store, limiter, services = setup_dispatcher(tmp_path, per_user_seconds=30)
    for mode, responses in [("single", ["Single {sender}"]), ("random", ["One", "Two"])]:
        raw = burst_payload(name=mode, aliases=[], response_mode=mode, responses=responses, permission="USER")
        del raw["burst_count"], raw["burst_allow_override"]
        store.save(raw)
    respond = AsyncMock()
    await dispatcher.dispatch(message("!single", respond), services)
    assert respond.await_args.args == ("Single caller",)
    await dispatcher.dispatch(message("!random", respond), services)
    assert respond.await_count == 1
    await dispatcher.dispatch(message("!promo", respond, is_moderator=True), services)
    assert respond.await_count == 6
    await dispatcher.dispatch(message("!promotion", respond, is_moderator=True), services)
    assert respond.await_count == 6  # Aliases share the same command cooldown.
    saved = store.get_by_name("promo")
    store.save({**saved.to_json(), "enabled": False, "per_user_seconds": 0})
    await dispatcher.dispatch(message("!promo", respond, is_moderator=True), services)
    assert respond.await_count == 6
    assert not limiter.try_acquire()
