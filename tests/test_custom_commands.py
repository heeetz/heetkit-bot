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


@pytest.mark.asyncio
async def test_manual_broadcaster_using_bot_account_executes_custom_alias(tmp_path):
    store = CustomCommandStore(tmp_path / "commands.json", set())
    store.save(payload(responses=["Hello {sender}"]))
    replies = []
    async def respond(content):
        replies.append(content)
    message = IncomingChatMessage("channel", "!hello", ChatAuthor("100", "broadcaster", is_broadcaster=True), respond)
    dispatcher = CommandDispatcher(CommandRegistry(), CooldownManager(), logging.getLogger(__name__), "!", custom_commands=store)
    assert await dispatcher.dispatch(message, SimpleNamespace(settings=SimpleNamespace(twitch_bot_user_id="100")))
    assert replies == ["Hello broadcaster"]


def payload(**changes):
    command = {
        "name": "Greet", "enabled": True, "responses": ["Hi {sender}, {target}: {args} {arg2} {random_user}"],
        "permission": "USER", "per_user_seconds": 0, "global_seconds": 0, "aliases": ["hello"],
    }
    return {**command, **changes}


@pytest.mark.parametrize("case", ["enabled", "disabled", "customized", "absent"])
@pytest.mark.asyncio
async def test_legacy_tg_converts_once_to_an_ordinary_burst_command(tmp_path, case):
    from app.fun_settings import FunSettingsStore
    from app.legacy_tg import migrate_tg
    from app.twitch.permissions import Permission

    fun_path, settings_path = tmp_path / "fun_settings.json", tmp_path / "command_settings.json"
    message_text = "My {sender} community" if case == "customized" else "My community"
    if case != "absent":
        fun_path.write_text(json.dumps({"version": 1, "fates": ["Keep fate"],
                                      **({"tg_message": message_text} if case != "enabled" else {})}), encoding="utf-8")
        settings_path.write_text(json.dumps({"tg": {
            "enabled": case != "disabled", "permission": "BROADCASTER",
            "cooldown": {"per_user_seconds": 2, "global_seconds": 5},
            "aliases": ["community"], "burst_max_count": 20, "burst_interval_ms": 200,
        }}), encoding="utf-8")
    custom_path = tmp_path / "custom_commands.json"
    store = CustomCommandStore(custom_path, set())
    migrate_tg(store, fun_path, settings_path)
    saved = store.list()
    if case == "absent":
        assert saved == ()
        assert not custom_path.exists()
        return
    command, = saved
    assert (command.name, command.response_mode, command.enabled) == ("tg", "burst", case != "disabled")
    expected_text = "Configure your community link in config/fun_settings.json." if case == "enabled" else message_text
    assert render_response(command, "", "owner", "owner") == expected_text
    assert command.permission == Permission.BROADCASTER
    assert (command.cooldown.per_user_seconds, command.cooldown.global_seconds) == (2, 5)
    assert command.aliases == ("community",)
    assert (command.burst_count, command.burst_allow_override, command.burst_max_count, command.burst_interval_ms) == (1, True, 20, 200)
    assert json.loads(fun_path.read_text()) == {"version": 1, "fates": ["Keep fate"]}
    assert "tg" not in json.loads(settings_path.read_text())
    assert FunSettingsStore(fun_path).fates == ("Keep fate",)
    restarted = CustomCommandStore(custom_path, set())
    migrate_tg(restarted, fun_path, settings_path)
    assert restarted.list() == saved
    replies = []
    async def respond(content):
        replies.append(content)
    message = IncomingChatMessage("channel", "!community 2", ChatAuthor("100", "owner", is_broadcaster=True), respond)
    dispatcher = CommandDispatcher(CommandRegistry(), CooldownManager(), logging.getLogger(__name__), "!", custom_commands=restarted)
    assert await dispatcher.dispatch(message, SimpleNamespace(settings=SimpleNamespace(twitch_bot_user_id="200")))
    assert replies == ([expected_text] * 2 if command.enabled else [])


@pytest.mark.parametrize("changes,code,params", [
    ({"enabled": 1}, "validation.type", {"field": "enabled", "expected": "boolean"}),
    ({"per_user_seconds": -1}, "validation.minimum", {"field": "per_user_seconds", "limit": "0"}),
    ({"global_seconds": 86401}, "validation.maximum", {"field": "global_seconds", "limit": "86400"}),
    ({"responses": ["x" * 2001]}, "validation.too_long", {"field": "responses", "max": "2000"}),
    ({"name": "two words"}, "validation.text", {"field": "name"}),
])
def test_model_constraints_reject_edits_without_writing(tmp_path, changes, code, params):
    from app.errors import UserError

    path = tmp_path / "commands.json"
    store = CustomCommandStore(path, set())
    saved = store.save(payload())
    before = path.read_bytes()
    with pytest.raises(UserError) as error:
        store.save({**saved.to_json(), **changes})
    assert (error.value.code, error.value.params) == (code, params)
    assert store.list() == (saved,)
    assert path.read_bytes() == before


def test_store_normalizes_aliases_rejects_collisions_and_persists(tmp_path) -> None:
    path = tmp_path / "custom_commands.json"
    store = CustomCommandStore(path, {"ping", "p"})
    saved = store.save(payload())
    assert store.get_by_name("HELLO") == saved
    assert store.get_by_name("!gReEt") == saved
    assert saved.response_mode == "single"
    assert CustomCommandStore(path, {"ping", "p"}).get_by_name("greet") == saved
    with pytest.raises(ValueError) as error:
        store.save(payload(name="Ping"))
    assert error.value.code == "custom_commands.command_name_alias_already_exists"
    with pytest.raises(ValueError) as error:
        store.save(payload(name="other", aliases=["HELLO"]))
    assert error.value.code == "custom_commands.command_name_alias_already_exists"
    with pytest.raises(ValueError) as error:
        store.save(payload(aliases=["GREET"]))
    assert error.value.code == "custom_commands.command_name_aliases_unique"
    with pytest.raises(ValueError) as error:
        store.save(payload(responses=["{execute}"]))
    assert error.value.code == "custom_commands.response_contains_unknown_variable"
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


@pytest.mark.parametrize("count", [1, 10, 11, 30])
def test_random_pool_saves_and_reloads_all_templates(tmp_path, count):
    path = tmp_path / "commands.json"
    responses = [f"Reply {index} to {{sender}}" for index in range(count)]
    saved = CustomCommandStore(path, set()).save(payload(response_mode="random", responses=responses))
    assert saved.responses == tuple(responses)
    assert CustomCommandStore(path, set()).get_by_name("hello") == saved


@pytest.mark.parametrize("responses", [[], ["Reply"] * 31])
def test_random_pool_invalid_size_rejected_without_changing_saved_command(tmp_path, responses):
    path = tmp_path / "commands.json"
    store = CustomCommandStore(path, set())
    saved = store.save(payload(response_mode="random", responses=["Reply"] * 30))
    before = path.read_bytes()
    with pytest.raises(ValueError) as error:
        store.save({**saved.to_json(), "responses": responses})
    assert error.value.code == ("validation.minimum" if not responses else "validation.too_many")
    assert error.value.params["field"] == "responses"
    assert store.list() == (saved,)
    assert path.read_bytes() == before


@pytest.mark.parametrize("changes,match", [
    ({"response_mode": "single", "responses": ["Reply"] * 30}, "custom_commands.single_burst_modes_require_exactly_one"),
    ({"response_mode": "burst", "permission": "MODERATOR", "responses": ["Reply"] * 30}, "custom_commands.single_burst_modes_require_exactly_one"),
    ({"aliases": [f"alias{index}" for index in range(11)]}, "validation.too_many"),
    ({"responses": ["Reply"] * 29 + ["x" * 2001]}, "validation.too_long"),
])
def test_larger_random_pool_preserves_other_custom_limits(tmp_path, changes, match):
    with pytest.raises(ValueError) as error:
        CustomCommandStore(tmp_path / "commands.json", set()).save(payload(**changes))
    assert error.value.code == match


@pytest.mark.asyncio
async def test_dispatch_selects_from_entire_thirty_template_pool(tmp_path, monkeypatch):
    store = CustomCommandStore(tmp_path / "commands.json", set())
    responses = [f"Reply {index} to {{sender}}" for index in range(29)] + ["{sender} " + "😀" * 200]
    store.save(payload(response_mode="random", responses=responses))
    choices = []

    def choose(values):
        assert tuple(values) == tuple(responses)
        choices.append(values)
        return values[-1]

    monkeypatch.setattr("app.commands.registry.random.choice", choose)
    replies = []

    async def respond(content):
        replies.append(content)

    dispatcher = CommandDispatcher(CommandRegistry(), CooldownManager(), logging.getLogger(__name__), "!",
                                   custom_commands=store)
    message = IncomingChatMessage("channel", "!hello", ChatAuthor("viewer-id", "viewer"), respond)
    assert await dispatcher.dispatch(message, SimpleNamespace(settings=SimpleNamespace(twitch_bot_user_id="bot-id")))
    assert len(choices) == len(replies) == 1
    assert replies[0].startswith("viewer 😀")
    assert len(replies[0].encode("utf-8")) <= 450


def test_malformed_file_skips_bad_entries_and_never_blocks_builtins(tmp_path) -> None:
    path = tmp_path / "custom_commands.json"
    good = CustomCommandStore(path, set()).save(payload())
    path.write_text(json.dumps({"version": 2, "commands": [{**good.to_json(), "name": "ping"},
                                                  good.to_json(), {**good.to_json(), "id": "bad"}]}), encoding="utf-8")
    store = CustomCommandStore(path, {"ping"})
    assert store.list() == (good,)
    path.write_text("{bad", encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()
    path.write_text('{"version": 99, "commands": []}', encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()
    path.write_text('{"version": true, "commands": []}', encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()
    path.write_text(json.dumps({"version": 2, "commands": [{**good.to_json(), "per_user_seconds": 10 ** 1000}]}), encoding="utf-8")
    assert CustomCommandStore(path, {"ping"}).list() == ()


@pytest.mark.parametrize("mode,responses", [("single", ["Hello"]), ("random", ["Only one"]),
                                           ("random", ["One", "Two"]), ("burst", ["Hello {target}"])])
def test_explicit_modes_and_burst_configuration_persist_across_restart(tmp_path, mode, responses):
    path = tmp_path / "commands.json"
    extra = {"burst_count": 7, "burst_max_count": 20, "burst_allow_override": True} if mode == "burst" else {}
    saved = CustomCommandStore(path, set()).save(payload(
        response_mode=mode, responses=responses, permission="MODERATOR", **extra))
    assert saved.response_mode == mode
    restarted = CustomCommandStore(path, set())
    assert restarted.list() == (saved,)
    assert saved.to_json()["response_mode"] == mode
    assert ("burst_count" in saved.to_json()) == (mode == "burst")
    restarted.save({**saved.to_json(), "enabled": False})
    assert list(tmp_path.glob("*.recovery")) == []


@pytest.mark.parametrize("changes", [
    {"burst_count": 0}, {"burst_count": 11}, {"burst_count": -1}, {"burst_count": True},
    {"burst_count": 1.5}, {"burst_count": "5"}, {"burst_count": None},
    {"burst_max_count": 0}, {"burst_max_count": 21}, {"burst_max_count": True},
    {"burst_max_count": "10"}, {"burst_max_count": 4},
    {"burst_allow_override": "true"}, {"burst_allow_override": 1},
    {"response_mode": "invalid"}, {"response_mode": None}, {"response_mode": {}},
    {"permission": "USER"}, {"permission": "SUBSCRIBER"}, {"permission": "VIP"},
    {"responses": ["One", "Two"]}, {"responses": ["{invalid}"]},
    {"responses": ["Broken {"]}, {"responses": ["two\nlines"]},
    {"response_mode": "single"},  # Burst fields cannot accompany another mode.
])
def test_invalid_burst_configuration_rejected_by_save_and_load(tmp_path, changes):
    from uuid import uuid4

    path = tmp_path / "commands.json"
    raw = {
        **payload(response_mode="burst", permission="MODERATOR", burst_count=5, burst_allow_override=True), **changes,
    }
    store = CustomCommandStore(path, set())
    with pytest.raises(ValueError):
        store.save(raw)
    assert store.list() == ()
    assert not path.exists()
    path.write_text(json.dumps({"version": 2, "commands": [{**raw, "id": str(uuid4())}]}), encoding="utf-8")
    assert CustomCommandStore(path, set()).list() == ()


def test_bridge_exposes_modes_defaults_and_reports_invalid_burst(tmp_path):
    from app.webview_host import WebUIBridge

    store = CustomCommandStore(tmp_path / "commands.json", set())
    bridge = WebUIBridge(SimpleNamespace(application=SimpleNamespace(
        custom_commands=store, settings=SimpleNamespace(command_prefix="!"))))
    raw = payload(response_mode="burst", permission="MODERATOR")
    assert bridge.save_custom_command(raw) == {"ok": True}
    command = bridge.get_custom_commands()["commands"][0]
    assert command["response_mode"] == "burst"
    assert command["burst_count"] == 1
    assert command["burst_allow_override"] is False
    assert bridge.save_custom_command({**command, "permission": "USER"})["ok"] is False
    assert bridge.delete_custom_command(command["id"]) == {"ok": True}


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
