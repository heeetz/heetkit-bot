"""Account blocks stop Ask before content logging, cooldowns, memory or provider work."""

import asyncio
import json
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ai_user_blocks import AIUserBlocklist
from app.commands.ai import register_ai_commands
from app.commands.fun import register_fun_commands
from app.commands.info import register_info_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.runtime_state import RuntimeState
from app.fun_settings import FunSettingsStore
from app.services.ai_request_policy import AIRequestPolicy
from app.services.contracts import AIReply
from app.services.filter_manager import FilterManager
from app.services.twitch import TwitchAPIService
from app.twitch.client import process_twitch_message
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager
from app.webview_host import WebUIBridge


def setup(root):
    registry = CommandRegistry()
    register_ai_commands(registry)
    register_info_commands(registry)
    register_fun_commands(registry, FunSettingsStore(root / "fun.json"))
    with_alias = CommandRegistry()
    for definition in registry.definitions():
        with_alias.register(replace(definition, aliases=("question",)) if definition.name == "ask" else definition)
    state = RuntimeState(command_settings_path=root / "commands.json")
    state.configure_commands(with_alias.definitions())
    blocks = AIUserBlocklist(root / "ai_user_blocks.json")
    cooldowns = CooldownManager()
    services = SimpleNamespace(
        ai_user_blocks=blocks, runtime_state=state, settings=SimpleNamespace(command_prefix="!"),
        users=SimpleNamespace(get_by_username=AsyncMock(return_value=None), upsert_seen=AsyncMock()),
        ai=SimpleNamespace(is_available=True, generate_reply=AsyncMock(return_value=AIReply("Answer", True))),
        ai_request_policy=AIRequestPolicy(), filter_manager=FilterManager(), twitch=None,
        memory=SimpleNamespace(get_recent=AsyncMock(return_value=[]), format_context=Mock(return_value=""), save_exchange=AsyncMock()),
    )
    dispatcher = CommandDispatcher(with_alias, cooldowns, logging.getLogger("tests.ai.blocks"), "!", runtime_state=state)
    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(services=services)))
    return blocks, services, dispatcher, bridge, state


def message(content="!ask A private question", *, username="viewer", user_id="123"):
    return IncomingChatMessage("channel", content, ChatAuthor(user_id, username, is_moderator=True), AsyncMock())


def test_crud_normalization_id_matching_and_profile_restart(tmp_path):
    blocks = AIUserBlocklist(tmp_path / "one" / "blocks.json")
    blocks.block(" @ViEwEr ", "123")
    assert blocks.list()[0].username == "viewer"
    assert blocks.is_blocked("123", "renamed")
    assert not blocks.is_blocked("456", "viewer")  # A reused login/display name is not the original account.
    for username, user_id in [("VIEWER", None), ("renamed", "123")]:
        with pytest.raises(ValueError, match="already blocked"):
            blocks.block(username, user_id)
    assert AIUserBlocklist(tmp_path / "one" / "blocks.json").list() == blocks.list()
    assert AIUserBlocklist(tmp_path / "two" / "blocks.json").list() == ()
    blocks.unblock("@VIEWER")
    assert not blocks.is_blocked("123", "viewer")
    assert AIUserBlocklist(tmp_path / "one" / "blocks.json").list() == ()


def test_observed_id_already_blocked_does_not_create_duplicate_id_entries(tmp_path):
    path = tmp_path / "blocks.json"
    blocks = AIUserBlocklist(path)
    blocks.block("original", "123")
    blocks.block("future_name")
    original = path.read_bytes()
    blocks.remember_observed_id("future_name", "123")
    assert path.read_bytes() == original
    assert AIUserBlocklist(path).list() == blocks.list()


@pytest.mark.parametrize("username", ["", " ", "@", "@@viewer", "bad name", "bad-name", "éviewer", "a" * 26, None, 123])
def test_invalid_logins_do_not_write(username, tmp_path):
    path = tmp_path / "blocks.json"
    blocks = AIUserBlocklist(path)
    with pytest.raises(ValueError):
        blocks.block(username)
    assert blocks.list() == () and not path.exists()


@pytest.mark.parametrize("content", ["!ask A private question", "!question A private question", "!savedalias A private question"])
async def test_blocked_requests_and_aliases_never_reach_ai_memory_cooldowns_or_reply(tmp_path, content, caplog):
    blocks, services, dispatcher, _, state = setup(tmp_path)
    state._command_settings["ask"] = replace(state.get_command_settings("ask"), aliases=("question", "savedalias"))
    blocks.block("viewer", "123")
    services.ai_request_policy.check = Mock(side_effect=services.ai_request_policy.check)
    dispatcher._cooldowns.check_and_record = Mock(side_effect=dispatcher._cooldowns.check_and_record)
    incoming = message(content)
    with caplog.at_level(logging.INFO):
        assert await dispatcher.dispatch(incoming, services)
    services.ai_request_policy.check.assert_not_called()
    services.ai.generate_reply.assert_not_awaited()
    services.memory.get_recent.assert_not_awaited()
    services.memory.save_exchange.assert_not_awaited()
    dispatcher._cooldowns.check_and_record.assert_not_called()
    incoming.respond.assert_not_awaited()
    assert "A private question" not in caplog.text
    assert [record.event_reason for record in caplog.records if hasattr(record, "event_reason")] == ["ai_user_blocked"]


async def test_unblocking_is_immediate_and_ignored_request_did_not_consume_global_cooldown(tmp_path):
    blocks, services, dispatcher, _, _ = setup(tmp_path)
    blocks.block("viewer", "123")
    incoming = message()
    await dispatcher.dispatch(incoming, services)
    blocks.unblock("viewer")
    await dispatcher.dispatch(incoming, services)
    services.ai.generate_reply.assert_awaited_once()
    services.memory.get_recent.assert_awaited_once()
    services.memory.save_exchange.assert_awaited_once()
    incoming.respond.assert_awaited_once()


async def test_other_commands_and_ordinary_messages_are_unaffected(tmp_path):
    blocks, services, dispatcher, _, _ = setup(tmp_path)
    blocks.block("viewer", "123")
    ping = message("!ping")
    assert await dispatcher.dispatch(ping, services)
    ping.respond.assert_awaited_once_with("pong")
    assert not await dispatcher.dispatch(message("ordinary chat"), services)
    services.ai.generate_reply.assert_not_awaited()


async def test_transport_guard_does_not_log_prompt_or_persist_user_and_latches_verified_id(tmp_path, caplog):
    blocks, services, dispatcher, _, _ = setup(tmp_path)
    blocks.block("viewer")
    twitch_message = SimpleNamespace(
        broadcaster=SimpleNamespace(name="channel"), text="!question PRIVATE SENTINEL",
        chatter=SimpleNamespace(id="123", name="ViEwEr", subscriber=False, vip=False, moderator=False, broadcaster=False),
        respond=AsyncMock(),
    )
    with caplog.at_level(logging.INFO):
        await process_twitch_message(twitch_message, services, dispatcher, logging.getLogger("tests.transport"))
    assert "PRIVATE SENTINEL" not in caplog.text
    assert "ai_user_blocked" in caplog.text
    services.users.upsert_seen.assert_not_awaited()
    services.ai.generate_reply.assert_not_awaited()
    services.memory.get_recent.assert_not_awaited()
    twitch_message.respond.assert_not_awaited()
    assert blocks.list()[0].twitch_user_id == "123"
    assert AIUserBlocklist(tmp_path / "ai_user_blocks.json").is_blocked("123", "renamed")


async def test_failed_id_capture_still_blocks_without_prompt_logging(tmp_path, monkeypatch, caplog):
    blocks, services, dispatcher, _, _ = setup(tmp_path)
    blocks.block("viewer")
    monkeypatch.setattr(blocks, "_save", Mock(side_effect=OSError("disk failure")))
    with caplog.at_level(logging.INFO):
        assert await dispatcher.dispatch(message("!ask PRIVATE SENTINEL"), services)
    assert "PRIVATE SENTINEL" not in caplog.text
    services.ai.generate_reply.assert_not_awaited()


def test_bridge_add_list_and_unblock_use_backend_and_observed_id(tmp_path, monkeypatch):
    blocks, services, _, bridge, _ = setup(tmp_path)
    services.users.get_by_username.return_value = SimpleNamespace(twitch_user_id="123")
    monkeypatch.setattr(bridge, "_wait_for_backend", lambda coro, **kwargs: asyncio.run(coro))
    assert bridge.get_blocked_ai_users() == {"ok": True, "users": []}
    assert bridge.block_ai_user("@VIEWER") == {"ok": True, "users": [{"username": "viewer", "has_user_id": True}]}
    assert blocks.list()[0].twitch_user_id == "123"
    assert bridge.block_ai_user("viewer")["ok"] is False
    assert bridge.unblock_ai_user("@viewer") == {"ok": True, "users": []}
    assert bridge.unblock_ai_user("viewer")["ok"] is False


async def test_bridge_prefers_resolved_account_id_and_falls_back_when_not_observed(tmp_path):
    blocks, services, _, bridge, _ = setup(tmp_path)
    services.twitch = SimpleNamespace(resolve_user_id=AsyncMock(return_value="789"))
    services.users.get_by_username.return_value = SimpleNamespace(twitch_user_id="123")
    await bridge._block_ai_user("viewer")
    assert blocks.list()[0].twitch_user_id == "789"
    services.users.get_by_username.assert_not_awaited()
    services.twitch.resolve_user_id.return_value = None
    services.users.get_by_username.return_value = None
    await bridge._block_ai_user("unseen")
    assert blocks.list()[1].twitch_user_id is None


async def test_twitch_id_resolution_uses_login_and_never_display_name():
    twitch = TwitchAPIService()
    assert await twitch.resolve_user_id("viewer") is None
    fetch = AsyncMock(return_value=[SimpleNamespace(id="123", name="different", display_name="viewer")])
    twitch.bind(SimpleNamespace(fetch_users=fetch), "channel", "bot")
    assert await twitch.resolve_user_id("viewer") is None
    fetch.return_value = [SimpleNamespace(id="123", name="viewer", display_name="Whatever")]
    assert await twitch.resolve_user_id("viewer") == "123"
    fetch.assert_awaited_with(logins=["viewer"], token_for="bot")
    fetch.side_effect = RuntimeError("offline")
    assert await twitch.resolve_user_id("viewer") is None


def test_unknown_and_invalid_settings_preserved_with_recovery_on_edit(tmp_path):
    path = tmp_path / "blocks.json"
    original = b'{"version":1,"users":[{"username":"viewer","future":true},{"username":"bad name"}],"future":{"retain":1}}'
    path.write_bytes(original)
    blocks = AIUserBlocklist(path)
    assert len(blocks.list()) == 1
    assert path.read_bytes() == original
    blocks.block("other")
    assert [copy.read_bytes() for copy in tmp_path.glob("*.recovery")] == [original]
    assert len(AIUserBlocklist(path).list()) == 2


@pytest.mark.parametrize("original", [b'{bad', b'{"version":2,"users":[]}', b'{"version":1,"users":[],"users":[]}'])
def test_malformed_future_duplicate_files_refuse_replacement(tmp_path, original):
    path = tmp_path / "blocks.json"
    path.write_bytes(original)
    blocks = AIUserBlocklist(path)
    with pytest.raises(ValueError):
        blocks.block("viewer")
    assert path.read_bytes() == original and blocks.list() == ()


def test_atomic_replace_failure_does_not_publish_or_lose_existing_block(tmp_path, monkeypatch):
    path = tmp_path / "blocks.json"
    blocks = AIUserBlocklist(path)
    blocks.block("viewer", "123")
    original = path.read_bytes()
    monkeypatch.setattr("pathlib.Path.replace", Mock(side_effect=OSError("Synthetic failure")))
    with pytest.raises(OSError):
        blocks.unblock("viewer")
    assert blocks.is_blocked("123", "viewer") and path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))
