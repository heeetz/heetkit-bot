"""Non-command output shares delivery, echo protection and connection ownership."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from twitchio import Client
from twitchio.exceptions import HTTPException

from app.bot_runtime import BotRuntime
from app.commands.registry import CommandContext, CommandDispatcher, CommandRegistry
from app.config.settings import Settings
from app.services.twitch import TwitchAPIService
from app.twitch.client import TwitchChatBot
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.twitch.sending import ChatSessionClosedError
from app.utils.cooldown import CooldownManager
from app.utils.output_limiter import OutputLimiter


def ready_service(responder=None, *, limiter=None):
    responder = responder or AsyncMock(return_value=SimpleNamespace(id="sent", sent=True))
    client = SimpleNamespace(create_partialuser=lambda channel: SimpleNamespace(send_message=responder))
    service = TwitchAPIService(output_limiter=limiter or OutputLimiter(interval=0))
    service.bind(client, "channel", "bot", channel_name="channelname")
    service.set_chat_ready(client, True)
    return service, client, responder


def context(service, client, responder):
    async def respond(content):
        return await service.chat_messages.send("bot", "channel", responder, content)

    message = IncomingChatMessage("channelname", "!ping", ChatAuthor("viewer", "viewer"), respond,
                                  send_session=service.chat_session(client))
    return CommandContext(message, SimpleNamespace(), logging.getLogger(__name__), service.output_limiter)


async def test_independent_send_uses_existing_sdk_user_auth_and_correlates_result(monkeypatch):
    client = Client(client_id="synthetic", client_secret="synthetic", bot_id="bot")
    post = AsyncMock(return_value={"data": [{"message_id": "sdk-result", "is_sent": True}]})
    monkeypatch.setattr(client._http, "post_chat_message", post)
    service = TwitchAPIService()
    service.bind(client, "channel", "bot")
    with pytest.raises(ChatSessionClosedError):
        service.chat_sender()
    service.set_chat_ready(client, True)
    try:
        assert await service.chat_sender().reply("ordinary chat")
        assert post.await_count == 1
        assert post.await_args.kwargs == {
            "broadcaster_id": "channel", "sender_id": "bot", "message": "ordinary chat",
            "reply_to_message_id": None, "token_for": "bot", "source_only": None, "pin": None,
        }
        assert await service.chat_messages.is_outgoing("bot", "channel", ("sdk-result",))
        assert not await service.chat_messages.is_outgoing("bot", "other-channel", ("sdk-result",))
        assert not await service.chat_messages.is_outgoing("other-bot", "channel", ("sdk-result",))
    finally:
        await service.unbind(client)
        await client.close(save_tokens=False)


async def test_highlighted_send_uses_sdk_user_auth_and_204_without_chat_quarantine(monkeypatch, caplog):
    client = Client(client_id="synthetic", client_secret="synthetic", bot_id="bot")
    post = AsyncMock(return_value=None)
    ordinary = AsyncMock()
    monkeypatch.setattr(client._http, "post_chat_announcement", post)
    monkeypatch.setattr(client._http, "post_chat_message", ordinary)
    service = TwitchAPIService(output_limiter=OutputLimiter(interval=0))
    service.bind(client, "channel", "bot")
    with pytest.raises(ChatSessionClosedError):
        service.announcement_sender()
    service.set_chat_ready(client, True)
    try:
        with caplog.at_level(logging.INFO):
            assert await service.announcement_sender().reply("Highlighted announcement")
        assert post.await_args.kwargs == {
            "broadcaster_id": "channel", "moderator_id": "bot", "message": "Highlighted announcement",
            "color": "primary", "token_for": "bot", "source_only": None,
        }
        ordinary.assert_not_awaited()
        assert not service.chat_messages.pending and not service.chat_messages.uncertain_until
        assert not await service.chat_messages.is_outgoing("bot", "channel", ("manual-message",))
        outgoing = [record for record in caplog.records if getattr(record, "event_kind", None) == "chat.outgoing"]
        assert len(outgoing) == 1 and outgoing[0].event_outcome == "confirmed_send"
    finally:
        await service.unbind(client)
        await client.close(save_tokens=False)


@pytest.mark.parametrize("transition", ["stop", "reconnect", "channel"])
async def test_highlighted_captured_sender_never_follows_a_changed_connection(transition):
    post = AsyncMock(return_value=None)
    client = SimpleNamespace(create_partialuser=lambda channel: SimpleNamespace(send_announcement=post))
    service = TwitchAPIService()
    service.bind(client, "channel", "bot")
    service.set_chat_ready(client, True)
    sender = service.announcement_sender()
    if transition == "stop":
        service.stop_chat()
    elif transition == "reconnect":
        service.set_chat_ready(client, False)
        service.set_chat_ready(client, True)
    else:
        service.bind(client, "new-channel", "bot")
        service.set_chat_ready(client, True)
    with pytest.raises(ChatSessionClosedError):
        await sender.reply("stale highlight")
    post.assert_not_awaited()
    assert service.output_limiter.try_acquire()
    await service.unbind(client)


@pytest.mark.parametrize("result,outcome", [
    (SimpleNamespace(id="sent", sent=True), "confirmed_send"),
    (SimpleNamespace(id="dropped", sent=False), "failed_send"),
    (None, "uncertain_send"),
    (SimpleNamespace(id="no-confirmation"), "uncertain_send"),
    (OSError("PRIVATE lost response"), "uncertain_send"),
    (HTTPException("PRIVATE rejection", status=429, extra={}), "failed_send"),
])
async def test_independent_send_preserves_delivery_results_and_safe_activity(result, outcome, caplog):
    async def respond(**kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    service, client, _ = ready_service(respond)
    with caplog.at_level(logging.INFO):
        if isinstance(result, Exception):
            with pytest.raises(type(result)):
                await service.chat_sender().reply("ordinary chat")
        else:
            assert await service.chat_sender().reply("ordinary chat") is (outcome == "confirmed_send")
    outgoing = [record for record in caplog.records if getattr(record, "event_kind", None) == "chat.outgoing"]
    assert len(outgoing) == 1 and outgoing[0].event_outcome == outcome
    assert outgoing[0].event_source == "announcement"
    assert outgoing[0].event_channel == "channelname"
    assert outgoing[0].event_response_id and outgoing[0].event_request_id
    assert "PRIVATE" not in caplog.text
    assert not service.chat_messages.pending
    assert bool(service.chat_messages.uncertain_until) is (
        outcome == "uncertain_send" and getattr(result, "id", None) is None)
    await service.unbind(client)


async def test_commands_and_independent_sends_share_limiter_but_bursts_keep_existing_bypass():
    now = [0.0]
    limiter = OutputLimiter(interval=5, clock=lambda: now[0])
    service, client, direct = ready_service(limiter=limiter)
    reply = AsyncMock(return_value=SimpleNamespace(id="reply", sent=True))
    command = context(service, client, reply)
    sender = service.chat_sender()
    assert await sender.reply("first")
    assert not await command.reply("limited command")
    reply.assert_not_awaited()
    now[0] = 5
    assert await command.reply("command")
    assert not await sender.reply("limited independent send")
    assert len(await command.reply_burst("burst", 3)) == 3
    assert direct.await_count == 1 and reply.await_count == 4
    assert not limiter.try_acquire()
    await service.unbind(client)


@pytest.mark.parametrize("transition", ["reconnect", "stop", "channel"])
async def test_captured_senders_and_late_command_replies_cannot_follow_new_connection(transition):
    limiter = OutputLimiter(interval=60)
    service, client, direct = ready_service(limiter=limiter)
    reply = AsyncMock()
    command, sender = context(service, client, reply), service.chat_sender()
    if transition == "reconnect":
        service.set_chat_ready(client, False)
        with pytest.raises(ChatSessionClosedError):
            service.chat_sender()
        service.set_chat_ready(client, True)
    elif transition == "stop":
        service.stop_chat()
        service.set_chat_ready(client, True)  # A late ready/welcome cannot undo Stop.
        with pytest.raises(ChatSessionClosedError):
            service.chat_sender()
    else:
        service.bind(client, "other-channel", "bot")
        service.set_chat_ready(client, True)
    with pytest.raises(ChatSessionClosedError):
        await sender.reply("stale")
    with pytest.raises(ChatSessionClosedError):
        await command.reply("late result")
    direct.assert_not_awaited()
    reply.assert_not_awaited()
    assert limiter.try_acquire()  # Stale work never consumes a fresh output slot.
    await service.unbind(client)


@pytest.mark.parametrize("burst", [False, True])
@pytest.mark.parametrize("transition", ["stop", "reconnect", "channel"])
async def test_connection_change_cancels_pending_http_and_timers_and_drains_cleanup(burst, transition):
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def blocked(*args, **kwargs):
        calls.append((args, kwargs))
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    service, client, _ = ready_service(blocked)
    command, sender = context(service, client, blocked), service.chat_sender()
    work = asyncio.create_task(command.reply_burst("burst", 5, interval_ms=1000)
                               if burst else sender.reply("ordinary chat"))
    await asyncio.wait_for(entered.wait(), 2)
    if transition == "stop":
        service.stop_chat()
    elif transition == "reconnect":
        service.set_chat_ready(client, False)
        service.set_chat_ready(client, True)
    else:
        service.bind(client, "other-channel", "bot")
        service.set_chat_ready(client, True)
    closing = asyncio.create_task(service.unbind(client))
    await asyncio.wait_for(cleaning.wait(), 2)
    try:
        assert not closing.done() and not work.done()
        release.set()
        await asyncio.wait_for(closing, 2)
        with pytest.raises(asyncio.CancelledError):
            await work
        assert len(calls) == 1
        assert not service._retiring_sends and not service.chat_messages.pending
        assert await service.chat_messages.is_outgoing("bot", "channel", ("lost-result",))
        with pytest.raises(ValueError, match="not ready"):
            await service.begin_authorization()
    finally:
        release.set()
        await asyncio.gather(work, closing, return_exceptions=True)


async def test_old_client_cannot_reenable_or_unbind_new_channel():
    service, old_client, _ = ready_service()
    sender = service.chat_sender()
    new_send = AsyncMock(return_value=SimpleNamespace(id="new-id", sent=True))
    new_client = SimpleNamespace(create_partialuser=lambda channel: SimpleNamespace(send_message=new_send))
    service.bind(new_client, "new-channel", "bot")
    service.set_chat_ready(new_client, True)
    service.set_chat_ready(old_client, False)
    service.set_chat_ready(old_client, True)
    await service.unbind(old_client)
    with pytest.raises(ChatSessionClosedError):
        await sender.reply("old")
    assert await service.chat_sender().reply("new")
    assert service._client is new_client
    assert await service.chat_messages.is_outgoing("bot", "new-channel", ("new-id",))
    await service.unbind(new_client)


async def test_invalidation_before_send_task_starts_never_calls_http():
    service, client, direct = ready_service()
    sender = service.chat_sender()
    work = asyncio.create_task(sender.reply("stale"))
    await asyncio.sleep(0)  # The session owns the operation; its HTTP work has not begun.
    service.stop_chat()
    await service.unbind(client)
    with pytest.raises(asyncio.CancelledError):
        await work
    direct.assert_not_awaited()
    assert not service.chat_messages.pending and not service.chat_messages.uncertain_until


async def test_runtime_stop_invalidates_senders_before_returning():
    service, client, direct = ready_service()
    sender = service.chat_sender()
    application = SimpleNamespace(services=SimpleNamespace(twitch=service, runtime_state=SimpleNamespace()))
    runtime = BotRuntime(application, logging.getLogger(__name__))
    runtime.request_stop()
    with pytest.raises(ChatSessionClosedError):
        await sender.reply("stale")
    direct.assert_not_awaited()
    await service.unbind(client)


async def test_noncommand_echo_waits_for_pending_send_and_never_dispatches_or_triggers():
    settings = Settings(_env_file=None, twitch_client_id="synthetic", twitch_client_secret="synthetic",
                        twitch_bot_user_id="100", twitch_bot_username="bot",
                        twitch_channel_user_id="200", twitch_channel="channelname")
    service = TwitchAPIService(output_limiter=OutputLimiter(interval=0))
    entered, release = asyncio.Event(), asyncio.Event()
    users = SimpleNamespace(upsert_seen=AsyncMock())
    filters = SimpleNamespace(filter_message=lambda content: True)
    services = SimpleNamespace(twitch=service, settings=settings, runtime_state=None, users=users,
                               filter_manager=filters)
    registry = CommandRegistry()
    handler = AsyncMock()
    registry.command("ping")(handler)
    trigger = SimpleNamespace(id="reaction", enabled=True, probability=1, cooldown_seconds=0,
                              responses=["reaction"], matches=lambda content: True)
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!",
                                   message_triggers=SimpleNamespace(list=lambda: [trigger]))
    bot = TwitchChatBot(settings, settings.primary_account, services, dispatcher, logging.getLogger(__name__))

    async def post(**kwargs):
        entered.set()
        await release.wait()
        return {"data": [{"message_id": "sent", "is_sent": True}]}

    bot._http.post_chat_message = post
    bot._http._tokens["100"] = {}
    await bot.event_ready()
    sending = asyncio.create_task(service.chat_sender().reply("!ping"))
    await asyncio.wait_for(entered.wait(), 2)
    responses = AsyncMock(return_value=SimpleNamespace(id="manual-response", sent=True))
    raw = SimpleNamespace(id="sent", source_id=None, text="!ping", respond=responses,
                          broadcaster=SimpleNamespace(id="200", name="channelname"),
                          chatter=SimpleNamespace(id="100", name="bot", subscriber=False, vip=False,
                                                  moderator=False, broadcaster=False))
    echo = asyncio.create_task(bot.event_message(raw))
    try:
        await asyncio.sleep(0)
        assert not echo.done()
        release.set()
        assert await sending
        await echo
        handler.assert_not_awaited()
        responses.assert_not_awaited()
        users.upsert_seen.assert_not_awaited()
        # Equal text with a different ID is still a manually authored command.
        raw.id = "manual"
        await bot.event_message(raw)
        handler.assert_awaited_once()
        # Non-command outgoing text must also never start a reaction.
        raw.id, raw.text = "echo-copy", "ordinary chat"
        raw.source_id = "sent"
        await bot.event_message(raw)
        responses.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(sending, echo, return_exceptions=True)
        await bot.close(save_tokens=False)


async def test_bot_reconnect_and_close_invalidate_captured_sender():
    settings = Settings(_env_file=None, twitch_client_id="synthetic", twitch_client_secret="synthetic",
                        twitch_bot_user_id="100", twitch_bot_username="bot",
                        twitch_channel_user_id="200", twitch_channel="channelname")
    from app.runtime_state import RuntimeState
    state = RuntimeState()
    state.set_bot_running(True)
    service = TwitchAPIService()
    services = SimpleNamespace(twitch=service, runtime_state=state)
    bot = TwitchChatBot(settings, settings.primary_account, services, object(), logging.getLogger(__name__))
    bot._http._tokens["100"] = {}
    try:
        await bot.event_websocket_welcome(SimpleNamespace(id="first"))
        await bot.event_ready()
        old = service.chat_sender()
        await bot.event_websocket_closed(SimpleNamespace(socket=SimpleNamespace(session_id="first")))
        with pytest.raises(ChatSessionClosedError):
            await old.reply("stale")
        await bot.event_websocket_welcome(SimpleNamespace(id="second"))
        recovered = service.chat_sender()
        # An old socket's close cannot invalidate the recovered connection.
        await bot.event_websocket_closed(SimpleNamespace(socket=SimpleNamespace(session_id="first")))
        assert service.chat_session(bot).active
        with pytest.raises(ChatSessionClosedError):
            await old.reply("still stale")
        await bot.close(save_tokens=False)
        with pytest.raises(ChatSessionClosedError):
            await recovered.reply("closed")
        assert service._client is None
    finally:
        await bot.close(save_tokens=False)
