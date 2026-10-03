"""Custom commands share dispatch policy while remaining validated local data."""

import json
import logging
from types import SimpleNamespace
from typing import cast

import pytest

from app.commands.registry import CommandDispatcher, CommandRegistry
from app.custom_commands import CustomCommandStore, render_response
from app.services.facade import ApplicationServices
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager
from app.utils.output_limiter import OutputLimiter


def payload(**changes):
    command = {
        "name": "Greet", "enabled": True, "responses": ["Hi {sender}, {target}: {args} {arg2} {random_user}"],
        "permission": "USER", "per_user_seconds": 0, "global_seconds": 0, "aliases": ["hello"],
    }
    return {**command, **changes}


def test_store_normalizes_aliases_rejects_collisions_and_persists(tmp_path) -> None:
    path = tmp_path / "custom_commands.json"
    store = CustomCommandStore(path, {"ping", "p"})
    saved = store.save(payload())
    assert store.get_by_name("HELLO") == saved
    assert store.get_by_name("!gReEt") == saved
    assert saved.response_mode == "single"
    assert CustomCommandStore(path, {"ping", "p"}).get_by_name("greet") == saved
    with pytest.raises(ValueError, match="already exists"):
        store.save(payload(name="Ping"))
    with pytest.raises(ValueError, match="already exists"):
        store.save(payload(name="other", aliases=["HELLO"]))
    with pytest.raises(ValueError, match="unique"):
        store.save(payload(aliases=["GREET"]))
    with pytest.raises(ValueError, match="unknown variable"):
        store.save(payload(responses=["{execute}"]))
    assert json.loads(path.read_text(encoding="utf-8"))["commands"] == [saved.to_json()]
    store.delete(saved.id)
    assert store.get_by_name("hello") is None


def test_templates_use_safe_fallbacks_and_bounded_output(tmp_path) -> None:
    command = CustomCommandStore(tmp_path / "commands.json", set()).save(
        payload(responses=["{sender}|{target}|{args}|{arg1}|{arg2}|{random_user}"])
    )
    assert render_response(command, "", "caller", "recent") == "caller|caller||||recent"
    assert render_response(command, "@alice other", "caller", "recent") == "caller|alice|@alice other|@alice|other|recent"
    assert render_response(command, "@", "caller", "recent") == "caller|caller|@|@||recent"
    long = CustomCommandStore(tmp_path / "long.json", set()).save(payload(responses=["x" * 1000]))
    assert len(render_response(long, "", "caller", "recent")) == 450
    emoji = CustomCommandStore(tmp_path / "emoji.json", set()).save(payload(responses=["😀" * 200]))
    assert len(render_response(emoji, "", "caller", "recent").encode("utf-8")) <= 450


def test_malformed_file_skips_bad_entries_and_never_blocks_builtins(tmp_path) -> None:
    path = tmp_path / "custom_commands.json"
    good = CustomCommandStore(path, set()).save(payload())
    path.write_text(json.dumps({"version": 1, "commands": [{**good.to_json(), "name": "ping"},
                                                  good.to_json(), {**good.to_json(), "id": "bad"}]}), encoding="utf-8")
    store = CustomCommandStore(path, {"ping"})
    assert store.list() == (good,)
    path.write_text("{bad", encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()
    path.write_text('{"version": 99, "commands": []}', encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()
    path.write_text('{"version": true, "commands": []}', encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()
    path.write_text(json.dumps({"version": 1, "commands": [{**good.to_json(), "per_user_seconds": 10 ** 1000}]}), encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()


@pytest.mark.asyncio
async def test_dispatch_alias_permission_cooldown_random_response_and_output_limit(tmp_path, monkeypatch) -> None:
    registry = CommandRegistry()
    @registry.command("ping")
    async def ping(context, arguments):
        await context.reply("pong")

    store = CustomCommandStore(tmp_path / "custom_commands.json", {"ping"})
    saved = store.save(payload(responses=["first {random_user}", "second {random_user}"],
                               permission="MODERATOR", per_user_seconds=30))
    chosen = iter(["first {random_user}", "alice"])
    monkeypatch.setattr("app.commands.registry.random.choice", lambda values: next(chosen))
    replies = []
    async def respond(content):
        replies.append(content)
    class Users:
        async def recent_usernames(self, **kwargs):
            assert kwargs["exclude_user_ids"] == ("viewer-id", "bot-id")
            return ["alice"]
    services = cast(ApplicationServices, SimpleNamespace(users=Users(), settings=SimpleNamespace(
        twitch_bot_user_id="bot-id", twitch_bot_username="bot")))
    dispatcher = CommandDispatcher(registry, CooldownManager(), logging.getLogger(__name__), "!",
                                   output_limiter=OutputLimiter(interval=0), custom_commands=store)
    def message(content, moderator=False):
        return IncomingChatMessage("channel", content, ChatAuthor("viewer-id", "viewer", is_moderator=moderator), respond)
    assert await dispatcher.dispatch(message("!HeLLo"), services)
    assert replies == []
    assert await dispatcher.dispatch(message("!HELLO", True), services)
    assert replies == ["first alice"]
    assert await dispatcher.dispatch(message("!greet", True), services)
    assert replies == ["first alice"]
    store.save({**saved.to_json(), "enabled": False})
    assert await dispatcher.dispatch(message("!greet", True), services)
    assert replies == ["first alice"]
    assert await dispatcher.dispatch(message("!ping"), services)
    assert replies[-1] == "pong"
