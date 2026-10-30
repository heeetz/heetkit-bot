"""Synthetic local policy: stable scope/identity, privacy and pre-execution gates."""

import asyncio
import json
import logging
from concurrent.futures import Future
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ai_user_blocks import AIUserBlocklist
from app.command_restrictions import CommandRestrictionStore, parse_restriction
from app.commands.ai import register_ai_commands
from app.commands.info import register_info_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore
from app.management import ApplicationManagement
from app.message_triggers import MessageTriggerStore
from app.runtime_state import RuntimeState
from app.services.ai_request_policy import AIRequestPolicy
from app.services.contracts import AIReply
from app.services.filter_manager import FilterManager
from app.twitch.client import process_twitch_message
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager
from app.utils.logging import OperatorActivityHandler, RecentLogBuffer
from app.utils.output_limiter import OutputLimiter
from app.webview_host import WebUIBridge

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
NOTE = "PRIVATE NOTE SENTINEL"


def data(**changes):
    return {"username": "viewer", "command_ids": ["ask"], "expires_at": None, "note": NOTE, **changes}


def save(store, **changes):
    store.save(data(**changes), channel_id="200", user_id="123", valid_command_ids={"ask", "ping", "custom:one"})
    return store.list()[-1]


@pytest.fixture
def clock(monkeypatch):
    value = [NOW]
    monkeypatch.setattr("app.command_restrictions.utcnow", lambda: value[0])
    monkeypatch.setattr("app.commands.registry.utcnow", lambda: value[0])
    return value


def test_persistence_expiry_boundaries_downtime_cleanup_and_profile_isolation(tmp_path, clock):
    path = tmp_path / "policy.json"
    store = CommandRestrictionStore(path)
    end = NOW + timedelta(hours=1)
    rule = save(store, expires_at=end.isoformat())
    assert rule.expires_at == end.isoformat()
    assert CommandRestrictionStore(path).match("200", "123", "ask") == rule
    assert not store.match("201", "123", "ask")
    assert not CommandRestrictionStore(tmp_path / "other-profile.json").match("200", "123", "ask")
    clock[0] = end - timedelta(microseconds=1)
    assert store.match("200", "123", "ask")
    clock[0] = end
    assert store.match("200", "123", "ask") is None
    restarted = CommandRestrictionStore(path)
    assert restarted.list() == ()
    assert NOTE not in path.read_text()
    assert not list(tmp_path.glob("*.recovery"))
    assert json.loads(path.read_text()) == {"version": 2, "restrictions": []}


@pytest.mark.parametrize("changes", [
    {"expires_at": "2026-12-01"}, {"expires_at": NOW.isoformat()},
    {"expires_at": (NOW + timedelta(days=367)).isoformat()}, {"expires_at": 123},
    {"note": "x" * 201}, {"note": "private\nline"}, {"note": "\ud800"},
    {"command_ids": ["optout"]}, {"command_ids": ["missing"]},
    {"command_ids": ["ask", "ask"]}, {"command_ids": "ask"}, {"command_ids": [{}]},
    {"channel_id": "login"}, {"twitch_user_id": "login"},
])
def test_reject_invalid_inputs_without_mutation(tmp_path, clock, changes):
    store = CommandRestrictionStore(tmp_path / "policy.json")
    rule = save(store)
    original = store._path.read_bytes()
    with pytest.raises(ValueError):
        if set(changes) & {"channel_id", "twitch_user_id"}:
            parse_restriction({**json.loads(original)["restrictions"][0], **changes})
        else:
            save(store, **changes)
    assert store.list() == (rule,)
    assert store._path.read_bytes() == original


@pytest.mark.parametrize("payload", ["{", '{"version":3,"restrictions":[]}',
    '{"version":true,"restrictions":[]}', '{"version":1,"restrictions":[{}]}',
    '{"version":1,"version":1,"restrictions":[]}', '{"version":1,"restrictions":[],"unknown":1}'])
def test_invalid_policy_refuses_startup_without_overwrite_or_private_error(tmp_path, payload):
    path = tmp_path / "policy.json"
    path.write_text(payload)
    with pytest.raises(ValueError, match="Back up and repair") as error:
        CommandRestrictionStore(path)
    assert NOTE not in str(error.value)
    assert path.read_text() == payload


def test_failed_save_and_remove_keep_memory_and_disk(tmp_path, monkeypatch):
    store = CommandRestrictionStore(tmp_path / "policy.json")
    rule = save(store)
    original = store._path.read_bytes()
    monkeypatch.setattr("app.command_restrictions.os.fsync", Mock(side_effect=OSError("failed")))
    with pytest.raises(OSError):
        save(store, id=rule.id, note="replacement")
    with pytest.raises(OSError):
        store.remove(rule.id)
    assert store.list() == (rule,)
    assert store._path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


@pytest.fixture
def core(tmp_path):
    registry = CommandRegistry()
    register_ai_commands(registry)
    register_info_commands(registry)
    state = RuntimeState(command_settings_path=tmp_path / "commands.json")
    state.configure_commands(registry.definitions())
    state.apply_command_settings("ask", primary_name="question", aliases=["q"])
    custom = CustomCommandStore(tmp_path / "custom.json", state.reserved_command_names(),
                                namespace_lock=state.command_namespace_lock)
    state.bind_custom_commands(custom)
    rules = CommandRestrictionStore(tmp_path / "policy.json")
    settings = SimpleNamespace(command_prefix="!", twitch_channel_user_id="200", twitch_bot_user_id="999",
                               twitch_bot_username="bot")
    services = SimpleNamespace(command_restrictions=rules, settings=settings, runtime_state=state,
        ai_user_blocks=AIUserBlocklist(tmp_path / "ai_blocks.json"),
        users=SimpleNamespace(get_by_username=AsyncMock(return_value=None), upsert_seen=AsyncMock(),
                              opt_out=AsyncMock(), is_storage_opted_out=AsyncMock(return_value=False)),
        twitch=SimpleNamespace(resolve_user_id=AsyncMock(return_value="123"), record_human_message=Mock()),
        ai=SimpleNamespace(is_available=True, generate_reply=AsyncMock(return_value=AIReply("Answer", True))),
        ai_request_policy=AIRequestPolicy(), filter_manager=FilterManager(),
        memory=SimpleNamespace(get_recent=AsyncMock(return_value=[]), format_context=Mock(return_value=""),
                               save_exchange=AsyncMock()))
    cooldowns = CooldownManager()
    cooldowns.check_and_record = Mock(wraps=cooldowns.check_and_record)
    limiter = OutputLimiter()
    limiter.try_acquire = Mock(wraps=limiter.try_acquire)
    logger = logging.getLogger("tests.restrictions")
    buffer = RecentLogBuffer()
    handler = OperatorActivityHandler(buffer)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    dispatcher = CommandDispatcher(registry, cooldowns, logger, "!", runtime_state=state,
        custom_commands=custom, output_limiter=limiter)
    app = SimpleNamespace(services=services, settings=settings, registry=registry, custom_commands=custom)
    management = ApplicationManagement(app, None)
    yield rules, services, dispatcher, state, custom, management, buffer
    logger.removeHandler(handler)


def message(content="!question PRIVATE PROMPT", **changes):
    return IncomingChatMessage("channel", content, ChatAuthor("123", "renamed"),
        AsyncMock(return_value=SimpleNamespace(sent=True, id="send")), channel_id="200", **changes)


@pytest.mark.parametrize("invocation", ["!question PRIVATE PROMPT", "!q PRIVATE PROMPT", "!newask PRIVATE PROMPT"])
async def test_alias_and_account_rename_guard_precedes_every_execution_boundary(core, invocation):
    rules, services, dispatcher, state, _, _, buffer = core
    save(rules)
    state.apply_command_settings("ask", primary_name="newask", aliases=["question", "q"])
    services.ai_request_policy.check = Mock(wraps=services.ai_request_policy.check)
    incoming = message(invocation)
    assert await dispatcher.dispatch(incoming, services)
    services.ai_request_policy.check.assert_not_called()
    services.ai.generate_reply.assert_not_awaited()
    services.memory.get_recent.assert_not_awaited()
    dispatcher._cooldowns.check_and_record.assert_not_called()
    dispatcher._output_limiter.try_acquire.assert_not_called()
    incoming.respond.assert_not_awaited()
    entries = buffer.activity()["entries"]
    assert len(entries) == 1
    assert entries[0]["context"]["reason"] == "personal_command_restriction"
    assert entries[0]["context"]["command_id"] == "ask"
    assert NOTE not in json.dumps(entries) and "PRIVATE PROMPT" not in json.dumps(entries)


async def test_reused_login_other_channel_and_immediate_remove(core):
    rules, services, dispatcher, _, _, _, _ = core
    rule = save(rules)
    assert not rules.match("200", "456", "ask")
    incoming = replace(message(), channel_id="201")
    assert not dispatcher.is_command_restricted(incoming, services)
    assert not dispatcher.is_command_restricted(replace(message(), author=ChatAuthor("456", "viewer")), services)
    await dispatcher.dispatch(message(), services)
    rules.remove(rule.id)
    assert await dispatcher.dispatch(message(), services)
    services.ai.generate_reply.assert_awaited_once()
    assert dispatcher._cooldowns.check_and_record.call_count == 1


async def test_custom_stable_id_survives_rename_aliases_and_restart(core):
    rules, services, dispatcher, _, custom, _, _ = core
    command = custom.save({"name": "greet", "enabled": True, "responses": ["hi"], "permission": "USER",
                           "per_user_seconds": 0, "global_seconds": 0, "aliases": ["hello"]})
    rules.save(data(command_ids=[f"custom:{command.id}"]), channel_id="200", user_id="123",
               valid_command_ids={f"custom:{command.id}"})
    renamed = custom.save({**command.to_json(), "name": "renamed", "aliases": ["hello"]})
    assert renamed.id == command.id
    services.command_restrictions = CommandRestrictionStore(rules._path)
    for name in ("renamed", "hello"):
        incoming = message("!" + name)
        assert await dispatcher.dispatch(incoming, services)
        incoming.respond.assert_not_awaited()
    dispatcher._cooldowns.check_and_record.assert_not_called()


async def test_all_rule_covers_reactions_and_future_commands_without_suppressing_ordinary_chat(core, tmp_path):
    rules, services, dispatcher, _, _, _, _ = core
    save(rules, command_ids=[])
    triggers = MessageTriggerStore(tmp_path / "triggers.json")
    triggers.save([{"id": "reaction", "enabled": True, "match_mode": "exact", "text": "hi",
        "case_sensitive": False, "probability": 1, "cooldown_seconds": 30, "responses": ["hello"]}])
    dispatcher._message_triggers = triggers
    dispatcher._custom_commands.save({"name": "future", "enabled": True, "responses": ["hi"],
        "permission": "USER", "per_user_seconds": 0, "global_seconds": 0, "aliases": []})
    for text in ("hi", "!commands", "!future", "!question PRIVATE PROMPT"):
        incoming = message(text)
        assert await dispatcher.dispatch(incoming, services)
        incoming.respond.assert_not_awaited()
    assert not dispatcher.is_command_restricted(message("ordinary message"), services)
    dispatcher._cooldowns.check_and_record.assert_not_called()


async def test_captured_command_and_reaction_guards_survive_a_stale_early_lookup(core, tmp_path, monkeypatch):
    rules, services, dispatcher, _, _, _, _ = core
    save(rules, command_ids=[])
    # A native edit may race the first lookup; actual captured identities are gated too.
    monkeypatch.setattr(dispatcher, "is_command_restricted", lambda *_: False)
    reaction = MessageTriggerStore(tmp_path / "triggers.json")
    reaction.save([{"id": "reaction", "enabled": True, "match_mode": "exact", "text": "hi",
        "case_sensitive": False, "probability": 1, "cooldown_seconds": 30, "responses": ["hello"]}])
    dispatcher._message_triggers = reaction
    for content in ("!q secret", "hi"):
        incoming = message(content)
        assert await dispatcher.dispatch(incoming, services)
        incoming.respond.assert_not_awaited()
    dispatcher._cooldowns.check_and_record.assert_not_called()
    dispatcher._output_limiter.try_acquire.assert_not_called()


async def test_ingress_restriction_keeps_private_input_out_of_presence_and_diagnostics(core):
    rules, services, dispatcher, _, _, _, buffer = core
    save(rules, expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    incoming = SimpleNamespace(broadcaster=SimpleNamespace(id="200", name="renamedchannel"),
        text="!q PRIVATE PROMPT", id="event", chatter=SimpleNamespace(id="123", name="renamed", subscriber=False,
        vip=False, moderator=False, broadcaster=False), respond=AsyncMock())
    await process_twitch_message(incoming, services, dispatcher, dispatcher._logger)
    services.users.upsert_seen.assert_not_awaited()
    services.twitch.record_human_message.assert_not_called()
    services.ai.generate_reply.assert_not_awaited()
    entry = buffer.activity()["entries"][0]
    assert 0 < entry["context"]["remaining_seconds"] <= 3600
    assert entry["text"] is None
    assert NOTE not in json.dumps(buffer.recent()) and "PRIVATE PROMPT" not in json.dumps(buffer.recent())


async def test_opted_out_viewer_keeps_restriction_diagnostics_suppressed(core):
    rules, services, dispatcher, _, _, _, buffer = core
    save(rules)
    services.users.is_storage_opted_out.return_value = True
    incoming = SimpleNamespace(broadcaster=SimpleNamespace(id="200", name="channel"), text="!q secret",
        chatter=SimpleNamespace(id="123", name="viewer", subscriber=False, vip=False, moderator=False,
                                broadcaster=False), respond=AsyncMock())
    await process_twitch_message(incoming, services, dispatcher, dispatcher._logger)
    assert buffer.activity()["entries"] == []
    services.ai.generate_reply.assert_not_awaited()


async def test_expiry_allows_first_request_without_replay_or_reserved_capacity(core, clock):
    rules, services, dispatcher, _, _, _, buffer = core
    save(rules, expires_at=(NOW + timedelta(seconds=1)).isoformat())
    await dispatcher.dispatch(message(), services)
    clock[0] = NOW + timedelta(seconds=1)
    await dispatcher.dispatch(message(), services)
    services.ai.generate_reply.assert_awaited_once()
    assert dispatcher._cooldowns.check_and_record.call_count == 1
    assert buffer.activity()["entries"][0]["context"]["remaining_seconds"] == 1


def test_overlapping_wider_rules_and_deleted_command_edits(core):
    rules, services, dispatcher, _, _, _, _ = core
    specific = save(rules)
    wider = save(rules, command_ids=[])
    rules.remove(specific.id)
    assert dispatcher.is_command_restricted(message(), services)
    rules.save(data(id=wider.id, command_ids=["custom:one"]), channel_id="201", user_id="456",
               valid_command_ids={"custom:one"})
    rules.save(data(id=wider.id, command_ids=["custom:one"], note="deleted command retained"),
               channel_id="201", user_id="456", valid_command_ids=set())
    assert rules.list()[0].channel_id == "200" and rules.list()[0].twitch_user_id == "123"


async def test_channel_change_and_cancelled_resolution_never_save_partial_policy(core):
    rules, services, _, _, _, management, _ = core
    async def changed(_):
        services.settings.twitch_channel_user_id = "201"
        return "123"
    services.twitch.resolve_user_id.side_effect = changed
    assert not (await management._save_command_restriction(data()))["ok"]
    assert rules.list() == ()
    services.twitch.resolve_user_id.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await management._save_command_restriction(data())
    assert not rules._path.exists()


async def test_optout_precedes_all_rules_and_global_ai_block_still_wins(core):
    rules, services, dispatcher, _, _, _, buffer = core
    rule = save(rules, command_ids=[])
    services.ai_user_blocks.block("viewer", "123")
    incoming = SimpleNamespace(broadcaster=SimpleNamespace(id="200", name="channel"), text="!optout 456",
        chatter=SimpleNamespace(id="123", name="viewer", subscriber=False, vip=False, moderator=False,
                                broadcaster=False), respond=AsyncMock())
    await process_twitch_message(incoming, services, dispatcher, dispatcher._logger)
    services.users.opt_out.assert_awaited_once_with("123", username="viewer")
    incoming.respond.assert_awaited_once()
    assert buffer.recent() == []
    assert rules.list() == (rule,)
    rules.remove(rule.id)
    assert await dispatcher.dispatch(message(), services)
    services.ai.generate_reply.assert_not_awaited()
    assert buffer.activity()["entries"][0]["context"]["reason"] == "ai_user_blocked"


async def test_management_resolution_edit_remove_and_unresolved_identity(core):
    rules, services, _, _, _, management, _ = core
    response = await management._save_command_restriction(data())
    assert response["ok"] and response["restrictions"][0]["twitch_user_id"] == "123"
    rule = rules.list()[0]
    services.settings.twitch_channel_user_id = "201"
    services.twitch.resolve_user_id.reset_mock()
    assert (await management._save_command_restriction(data(id=rule.id, command_ids=[], note="edited")))["ok"]
    assert rules.list()[0].channel_id == "200"
    services.twitch.resolve_user_id.assert_not_awaited()
    assert not (await management._save_command_restriction(data(id=rule.id, username="other")))["ok"]
    assert management.remove_command_restriction(rule.id)["restrictions"] == []
    services.twitch.resolve_user_id.return_value = None
    result = await management._save_command_restriction(data())
    assert not result["ok"] and "verified Twitch user ID" in result["error"]
    assert rules.list() == ()
    services.users.get_by_username.return_value = SimpleNamespace(twitch_user_id="456")
    assert (await management._save_command_restriction(data()))["ok"]
    assert rules.list()[0].twitch_user_id == "456"
    services.settings.twitch_channel_user_id = "nickname"
    assert not (await management._save_command_restriction(data()))["ok"]


def test_native_bridge_uses_shared_management(core, monkeypatch):
    _, _, _, _, _, management, _ = core
    backend = management._backend
    def submit(coroutine):
        future = Future()
        try:
            future.set_result(asyncio.run(coroutine))
        except Exception as error:
            future.set_exception(error)
        return future
    monkeypatch.setattr(backend, "submit", submit, raising=False)
    bridge = WebUIBridge(backend)
    result = bridge.save_command_restriction(data())
    assert result["ok"]
    assert bridge.get_command_restrictions() == management.get_command_restrictions()
    assert bridge.remove_command_restriction(result["restrictions"][0]["id"])["restrictions"] == []
