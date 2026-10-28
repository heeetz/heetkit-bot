"""Real SDK lifecycle events and ingress exercise every shared command send mode."""
import asyncio
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from twitchio.eventsub.websockets import Websocket
from twitchio.exceptions import WebsocketConnectionException

from app.commands.fun import register_fun_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.config.settings import Settings
from app.custom_commands import CustomCommandStore
from app.fun_settings import FunSettingsStore
from app.runtime_state import RuntimeState
from app.services.filter_manager import FilterManager
from app.services.twitch import TwitchAPIService
from app.twitch.client import TwitchChatBot
from app.twitch.message_correlation import ChatMessageCorrelation
from app.utils.cooldown import CooldownManager
from app.utils.logging import OperatorActivityHandler, RecentLogBuffer
from app.utils.output_limiter import OutputLimiter


async def turns():
    for _ in range(20):
        await asyncio.sleep(0)


class Sandbox:
    def __init__(self, path, monkeypatch):
        self.now = asyncio.get_running_loop().time()
        monkeypatch.setattr(asyncio.get_running_loop(), 'time', lambda: self.now)
        self.buffer = RecentLogBuffer()
        self.activity = OperatorActivityHandler(self.buffer)
        self.logger = logging.getLogger('tests.command.lifecycle')
        self.logger.addHandler(self.activity)
        self.logger.setLevel(logging.INFO)
        self.sent = []
        self.sockets = []
        settings = Settings(_env_file=None, _env_prefix='HEETKIT_SYNTHETIC_UNUSED_',
            twitch_client_id='synthetic', twitch_client_secret='synthetic', twitch_bot_user_id='100',
            twitch_bot_username='syntheticbot', twitch_channel_user_id='200', twitch_channel='syntheticchannel',
            twitch_token_file=str(path / 'unused-tokens.json'), database_url='sqlite+aiosqlite:///:memory:',
            gemini_api_key=None, deepseek_api_key=None, openai_api_key=None)
        self.state = RuntimeState()
        self.state.set_bot_running(True)
        self.twitch = TwitchAPIService(output_limiter=OutputLimiter(clock=lambda: self.now))
        self.twitch.chat_messages = ChatMessageCorrelation(clock=lambda: self.now)
        self.users = NS(is_storage_opted_out=AsyncMock(return_value=False), upsert_seen=AsyncMock())
        self.services = NS(settings=settings, twitch=self.twitch, users=self.users,
                           filter_manager=FilterManager(), runtime_state=self.state)
        registry = CommandRegistry()
        register_fun_commands(registry, FunSettingsStore(path / 'fun.json'))
        self.state.configure_commands(registry.definitions())
        self.custom = CustomCommandStore(path / 'custom.json', {d.name for d in registry.definitions()})
        for name, mode in [('single', 'single'), ('yt', 'burst')]:
            raw = dict(name=name, enabled=True, responses=['Synthetic reply'], permission='MODERATOR',
                       aliases=[], per_user_seconds=0, global_seconds=0, response_mode=mode)
            if mode == 'burst':
                raw.update(burst_count=1, burst_allow_override=True, burst_interval_ms=100)
            self.custom.save(raw)
        self.dispatcher = CommandDispatcher(registry, CooldownManager(clock=lambda: self.now), self.logger, '!',
            output_limiter=self.twitch.output_limiter, runtime_state=self.state, custom_commands=self.custom)
        self.bot = TwitchChatBot(settings, settings.primary_account, self.services, self.dispatcher, self.logger)
        self.bot._http._tokens['100'] = {}  # Synthetic token-map membership, never authentication.
        monkeypatch.setattr(self.bot._http, 'request', AsyncMock(side_effect=AssertionError('Network forbidden')))

    async def welcome(self, identifier):
        socket = Websocket(client=self.bot, token_for='100', http=self.bot._http)
        # A mocked transport listener; the SDK welcome handler and dispatch are real.
        socket._listen_task = asyncio.create_task(asyncio.Event().wait())
        self.sockets.append(socket)
        await socket._process_welcome(dict(payload=dict(session=dict(id=identifier,
            keepalive_timeout_seconds=30, connected_at='2026-10-28T00:00:00Z'))))
        await turns()
        return socket

    def event(self, content, mid, uid='100', responder=None):
        async def respond(text):
            self.sent.append((mid, text))
            return NS(id='sent-' + str(len(self.sent)), sent=True)
        return NS(id=mid, source_id=None, text=content,
            broadcaster=NS(id='200', name='syntheticchannel'),
            chatter=NS(id=uid, name='syntheticbot' if uid == '100' else 'syntheticviewer',
                moderator=True, subscriber=False, vip=False, broadcaster=False, badges=[]),
            respond=responder or respond)

    async def ingress(self, content, mid, uid='100', responder=None):
        task = asyncio.create_task(self.bot.event_message(self.event(content, mid, uid, responder)))
        await turns()
        for _ in range(4):
            self.now += .1
            await turns()
        await task

    def outcomes(self, mid):
        return [e['context'].get('outcome') for e in self.buffer.activity()['entries']
                if e['context'].get('input_message_id') == mid]

    async def close(self):
        await self.bot.close(save_tokens=False)
        for socket in self.sockets:
            await socket.close()
        await turns()
        self.logger.removeHandler(self.activity)


@pytest_asyncio.fixture
async def sandbox(tmp_path, monkeypatch):
    instance = Sandbox(tmp_path, monkeypatch)
    await instance.welcome('current')
    await instance.bot.event_ready()
    try:
        yield instance
    finally:
        await instance.close()


@pytest.mark.parametrize('command,count', [('!ping', 1), ('!tg 3', 3), ('!single', 1), ('!yt 3', 3)])
@pytest.mark.parametrize('idle', [0, 3600])
async def test_unwelcomed_secondary_socket_close_cannot_break_any_command(sandbox, command, count, idle):
    s = sandbox
    s.now += idle
    # Real SDK close event from a failed reconnect candidate, which never got a
    # session ID. It must not invalidate the already welcomed active connection.
    failed = Websocket(client=s.bot, token_for='100', http=s.bot._http)
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.ws_connect.side_effect = OSError('Synthetic failed reconnect candidate')
    with patch('twitchio.eventsub.websockets.aiohttp.ClientSession', return_value=session):
        with pytest.raises(WebsocketConnectionException):
            await failed.connect(url='wss://synthetic.invalid', fail_once=True)
    await turns()
    await s.ingress(command, 'manual')
    assert len(s.sent) == count
    assert 'handler_failed' not in s.outcomes('manual')
    assert s.state.twitch_connection_state == 'connected'


@pytest.mark.parametrize('command,count', [('!ping', 1), ('!tg 3', 3), ('!single', 1), ('!yt 3', 3)])
async def test_real_loss_then_welcome_recovers_every_command_and_preserves_old_sender(sandbox, command, count):
    s = sandbox
    original = s.twitch.chat_session(s.bot)
    await s.sockets[0].close()
    await turns()
    assert s.state.twitch_connection_state == 'reconnecting' and not original.active
    await s.ingress(command, 'during-loss')
    assert 'handler_failed' in s.outcomes('during-loss') and not s.sent
    failure = next(e for e in s.buffer.activity()['entries']
                   if e['context'].get('input_message_id') == 'during-loss'
                   and e['context'].get('outcome') == 'handler_failed')
    assert failure['context']['error_type'] == 'ChatSessionClosedError'
    assert failure['context']['stage'] == 'send_session'
    await s.welcome('recovered')
    assert s.state.twitch_connection_state == 'connected'
    assert not original.active and s.twitch.chat_session(s.bot) is not original
    s.now += 20
    await s.ingress(command, 'after-recovery')
    assert len(s.sent) == count and 'handler_failed' not in s.outcomes('after-recovery')


@pytest.mark.parametrize('command,count', [('!ping', 1), ('!tg 3', 3), ('!single', 1), ('!yt 3', 3)])
async def test_plain_inactivity_does_not_break_any_command(sandbox, command, count):
    s = sandbox
    s.now += 86400
    await s.ingress(command, 'after-idle')
    assert len(s.sent) == count and 'handler_failed' not in s.outcomes('after-idle')


@pytest.mark.parametrize('result', ['confirmed', 'network', 'reconnect'])
async def test_pending_and_uncertain_sends_remain_distinct_from_session_failures(sandbox, result):
    s = sandbox
    entered, release = asyncio.Event(), asyncio.Event()
    async def pending(_):
        entered.set()
        await release.wait()
        if result == 'network':
            raise OSError('PRIVATE transport details')
        return NS(id='first-output', sent=True)
    first = asyncio.create_task(s.bot.event_message(s.event('!single', 'first', '300', pending)))
    await entered.wait()
    manual = asyncio.create_task(s.bot.event_message(s.event('!tg', 'manual')))
    await turns()
    assert not manual.done() and s.outcomes('manual') == []
    await s.ingress('!tg', 'control', '400')
    assert 'confirmed_send' in s.outcomes('control')
    if result == 'reconnect':
        await s.sockets[0].close()
        await turns()
        await s.welcome('replacement')
    else:
        release.set()
    await asyncio.gather(first, manual, return_exceptions=True)
    if result == 'confirmed':
        assert 'confirmed_send' in s.outcomes('manual')
        assert not s.twitch.chat_messages.uncertain_until
    else:
        assert s.outcomes('manual') == []  # Dropped before COMMAND INPUT, no handler failure.
        assert s.twitch.chat_messages.uncertain_until
        await s.ingress('!tg', 'other-after-loss', '400')
        assert 'confirmed_send' in s.outcomes('other-after-loss')
        s.now += 600
        await turns()
        await s.ingress('!tg', 'manual-after-expiry')
        assert 'confirmed_send' in s.outcomes('manual-after-expiry')
    assert 'PRIVATE' not in str(s.buffer.activity())


async def test_delayed_ingress_never_retargets_a_captured_closed_session(sandbox):
    s = sandbox
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(**kwargs):
        entered.set()
        await release.wait()
    s.users.upsert_seen = delayed
    task = asyncio.create_task(s.bot.event_message(s.event('!yt 3', 'late')))
    await entered.wait()
    await s.sockets[0].close()
    await turns()
    await s.welcome('replacement')
    release.set()
    await task
    assert not s.sent and 'handler_failed' in s.outcomes('late')
    assert not s.twitch.chat_messages.uncertain_until


async def test_session_failure_metadata_respects_opt_out(sandbox):
    s = sandbox
    s.users.is_storage_opted_out.return_value = True
    await s.sockets[0].close()
    await turns()
    await s.ingress('!yt 3', 'private')
    assert not s.sent and s.outcomes('private') == []


async def test_failed_candidate_does_not_cancel_pending_send_or_create_quarantine(sandbox):
    s = sandbox
    entered, release = asyncio.Event(), asyncio.Event()
    async def pending(_):
        entered.set()
        await release.wait()
        return NS(id='confirmed-pending', sent=True)
    first = asyncio.create_task(s.bot.event_message(s.event('!single', 'pending', '300', pending)))
    await entered.wait()
    manual = asyncio.create_task(s.bot.event_message(s.event('!tg', 'manual')))
    await turns()
    candidate = Websocket(client=s.bot, token_for='100', http=s.bot._http)
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.ws_connect.side_effect = OSError('Synthetic failed candidate')
    with patch('twitchio.eventsub.websockets.aiohttp.ClientSession', return_value=session):
        with pytest.raises(WebsocketConnectionException):
            await candidate.connect(url='wss://synthetic.invalid', fail_once=True)
    await turns()
    assert not first.done() and not manual.done()
    release.set()
    await asyncio.gather(first, manual)
    assert 'confirmed_send' in s.outcomes('pending') and 'confirmed_send' in s.outcomes('manual')
    assert not s.twitch.chat_messages.uncertain_until
