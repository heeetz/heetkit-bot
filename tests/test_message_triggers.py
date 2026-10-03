"""Non-command reactions remain bounded, local, and subject to chat output policy."""

import json
import logging
from types import SimpleNamespace
from typing import cast

import pytest

from app.commands.registry import CommandDispatcher, CommandRegistry
from app.message_triggers import MessageTriggerStore
from app.runtime_paths import RuntimePaths, prepare_runtime_data
from app.services.facade import ApplicationServices
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager
from app.utils.output_limiter import OutputLimiter


def trigger(**changes):
    return {
        "id": "vas", "enabled": True, "match_mode": "contains", "text": "вась",
        "case_sensitive": False, "probability": 1, "cooldown_seconds": 30,
        "responses": ["first", "second"], **changes,
    }


def save(path, *triggers):
    path.write_text(json.dumps({"version": 1, "triggers": list(triggers)}), encoding="utf-8")
    return MessageTriggerStore(path)


def test_local_defaults_seed_and_remain_editable(tmp_path):
    paths = RuntimePaths(tmp_path / "appdata")
    prepare_runtime_data("missing-tokens", "sqlite+aiosqlite:///:memory:", paths=paths, legacy_data=tmp_path)
    seeded = MessageTriggerStore(paths.message_triggers).list()
    assert len(seeded) == 1
    assert seeded[0].text == "вась"
    save(paths.message_triggers, trigger(enabled=False))
    prepare_runtime_data("missing-tokens", "sqlite+aiosqlite:///:memory:", paths=paths, legacy_data=tmp_path)
    assert MessageTriggerStore(paths.message_triggers).list()[0].enabled is False


def test_validation_skips_bad_entries_and_bounds_matching(tmp_path):
    path = tmp_path / "message_triggers.json"
    store = save(path, trigger(), trigger(id="vas"), trigger(id="regex", match_mode="regex"),
                 trigger(id="bad", probability=float("nan")), trigger(id="other", responses=["x" * 451]))
    assert len(store.list()) == 1
    match = store.list()[0]
    assert match.matches("Эй ВАСЬ!")
    assert not match.matches("привет")
    assert save(path, trigger(match_mode="exact", case_sensitive=True, text="Hi")).list()[0].matches("Hi")
    assert not MessageTriggerStore(path).list()[0].matches("hi")
    path.write_text("{invalid", encoding="utf-8")
    assert MessageTriggerStore(path).list() == ()
    path.write_text('{"version": 99, "triggers": []}', encoding="utf-8")
    assert MessageTriggerStore(path).list() == ()


@pytest.mark.asyncio
async def test_trigger_dispatch_skips_commands_and_bot_and_reuses_cooldown_and_output_limit(tmp_path, monkeypatch):
    path = tmp_path / "message_triggers.json"
    store = save(path, trigger(), trigger(id="other", text="hello", cooldown_seconds=0))
    now = [0.0]
    responses = []

    async def respond(content):
        responses.append(content)

    services = cast(ApplicationServices, SimpleNamespace(settings=SimpleNamespace(twitch_bot_user_id="bot-id")))
    registry = CommandRegistry()
    dispatcher = CommandDispatcher(
        registry, CooldownManager(clock=lambda: now[0]), logging.getLogger(__name__), "!",
        output_limiter=OutputLimiter(interval=5, clock=lambda: now[0]), message_triggers=store,
    )
    monkeypatch.setattr("app.commands.registry.random.random", lambda: 0)
    monkeypatch.setattr("app.commands.registry.random.choice", lambda choices: choices[0])

    def message(content, user="viewer-id"):
        return IncomingChatMessage("channel", content, ChatAuthor(user, user), respond)

    assert not await dispatcher.dispatch(message("!unknown вась"), services)
    assert not await dispatcher.dispatch(message("вась", "bot-id"), services)
    assert await dispatcher.dispatch(message("ВАСЬ"), services)
    assert responses == ["first"]
    now[0] = 6
    assert not await dispatcher.dispatch(message("вась"), services)
    assert responses == ["first"]
    assert not await dispatcher.dispatch(message("вась", "second-viewer"), services)
    assert responses == ["first"]
    now[0] = 31
    assert await dispatcher.dispatch(message("вась"), services)
    assert responses == ["first", "first"]
    now[0] = 32
    assert await dispatcher.dispatch(message("hello"), services)
    assert responses == ["first", "first"]  # Shared output limiter blocks the second reaction.


@pytest.mark.asyncio
async def test_probability_and_disabled_trigger_do_not_send(tmp_path, monkeypatch):
    path = tmp_path / "message_triggers.json"
    store = save(path, trigger(id="off", enabled=False), trigger(id="rare", probability=0.1))
    replies = []

    async def respond(content):
        replies.append(content)

    services = cast(ApplicationServices, SimpleNamespace(settings=SimpleNamespace(twitch_bot_user_id="bot-id")))
    dispatcher = CommandDispatcher(CommandRegistry(), CooldownManager(), logging.getLogger(__name__), "!", message_triggers=store)
    monkeypatch.setattr("app.commands.registry.random.random", lambda: 0.9)
    message = IncomingChatMessage("channel", "вась", ChatAuthor("viewer-id", "viewer"), respond)
    assert not await dispatcher.dispatch(message, services)
    assert replies == []
