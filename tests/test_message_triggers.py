"""Non-command reactions remain bounded, local, and subject to chat output policy."""

import json
import logging
from types import SimpleNamespace
from typing import cast

import pytest

from app.commands.registry import CommandDispatcher, CommandRegistry
from app.message_triggers import MessageTriggerStore
from app.runtime_paths import DEFAULT_TRIGGERS, RuntimePaths, prepare_runtime_data
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
    assert not paths.root.exists()
    prepare_runtime_data("missing-tokens", "sqlite+aiosqlite:///:memory:", paths=paths, legacy_data=tmp_path)
    seeded = MessageTriggerStore(paths.message_triggers).list()
    assert seeded == ()
    assert paths.message_triggers.read_bytes() == DEFAULT_TRIGGERS.read_bytes()
    save(paths.message_triggers, trigger(enabled=False))
    prepare_runtime_data("missing-tokens", "sqlite+aiosqlite:///:memory:", paths=paths, legacy_data=tmp_path)
    assert MessageTriggerStore(paths.message_triggers).list()[0].enabled is False


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_utf8_with_bom_loads_like_utf8_without_bom(tmp_path, bom):
    path = tmp_path / "message_triggers.json"
    payload = json.dumps({"version": 1, "triggers": [trigger()]}, ensure_ascii=False)
    path.write_bytes(bom + payload.encode("utf-8"))

    loaded = MessageTriggerStore(path).list()

    assert len(loaded) == 1
    assert loaded[0].text == trigger()["text"]
    assert path.read_bytes() == bom + payload.encode("utf-8")


def test_valid_bom_file_can_be_edited_atomically(tmp_path):
    path = tmp_path / "message_triggers.json"
    path.write_text(json.dumps({"version": 1, "triggers": [trigger()]}), encoding="utf-8-sig")
    store = MessageTriggerStore(path)
    store.save([trigger(text="edited")])
    assert MessageTriggerStore(path).list()[0].text == "edited"


@pytest.mark.parametrize(
    "contents",
    (
        b"",
        b'{"version": 1,\n "triggers": [} /* PRIVATE REACTION */',
    ),
)
def test_corrupt_files_disable_reactions_preserve_bytes_and_log_json_location(
    tmp_path, caplog, contents
):
    paths = RuntimePaths(tmp_path / "profile")
    paths.config.mkdir(parents=True)
    path = paths.message_triggers
    path.write_bytes(contents)
    prepare_runtime_data("missing-tokens", "sqlite+aiosqlite:///:memory:", paths=paths, legacy_data=None)
    with pytest.raises(json.JSONDecodeError) as decoded:
        json.loads(contents)

    with caplog.at_level(logging.WARNING, logger="app.message_triggers"):
        assert MessageTriggerStore(path).list() == ()

    assert path.read_bytes() == contents
    assert str(path) in caplog.text
    assert f"line={decoded.value.lineno} column={decoded.value.colno} position={decoded.value.pos}" in caplog.text
    assert "PRIVATE REACTION" not in caplog.text


def test_invalid_utf8_diagnostic_does_not_include_content(tmp_path, caplog):
    path = tmp_path / "message_triggers.json"
    original = b'PRIVATE REACTION\xff'
    path.write_bytes(original)
    with caplog.at_level(logging.WARNING, logger="app.message_triggers"):
        assert MessageTriggerStore(path).list() == ()
    assert str(path) in caplog.text and "UnicodeDecodeError" in caplog.text
    assert "position=16" in caplog.text
    assert "PRIVATE REACTION" not in caplog.text and path.read_bytes() == original


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


@pytest.mark.parametrize(
    "payload, message",
    (
        ([trigger(id="one")] * 101, "at most 100"),
        ([trigger(), trigger(id="vas")], "Duplicate trigger ID"),
        ([trigger(future=True)], "Unknown trigger field"),
        (trigger(), "must be a list"),
    ),
)
def test_save_rejects_invalid_collections_without_replacing_existing_file(tmp_path, payload, message):
    path = tmp_path / "message_triggers.json"
    store = MessageTriggerStore(path)
    store.save([trigger()])
    original = path.read_bytes()
    before = store.list()

    with pytest.raises(ValueError, match=message):
        store.save(payload)

    assert path.read_bytes() == original
    assert store.list() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_save_persists_and_publishes_only_after_atomic_replace(tmp_path, monkeypatch):
    path = tmp_path / "message_triggers.json"
    store = MessageTriggerStore(path)
    store.save([trigger()])
    original = path.read_bytes()
    before = store.list()

    def fail_replace(*args, **kwargs):
        raise OSError("Synthetic replacement failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.message_triggers.os.replace", fail_replace)
        with pytest.raises(OSError, match="replacement failure"):
            store.save([trigger(id="other", text="hello")])

    assert path.read_bytes() == original
    assert store.list() == before
    assert not list(tmp_path.glob("*.tmp"))

    store.save([trigger(id="other", text="hello")])
    assert MessageTriggerStore(path).list()[0].id == "other"


def test_save_preserves_lossy_source_in_recovery_file(tmp_path):
    path = tmp_path / "message_triggers.json"
    original = (
        b'{"version":1,"triggers":[{"id":"vas","enabled":true,'
        b'"match_mode":"contains","text":"vas","case_sensitive":false,'
        b'"probability":1,"cooldown_seconds":30,"responses":["first"],'
        b'"future":true}],"future":{"retain":1}}'
    )
    path.write_bytes(original)
    store = MessageTriggerStore(path)

    store.save([trigger(text="vas", responses=["first"])])

    recovery = list(tmp_path.glob("*.recovery"))
    assert len(recovery) == 1
    assert recovery[0].read_bytes() == original
    assert MessageTriggerStore(path).list()[0].responses == ("first",)


def test_save_refuses_to_replace_unreadable_source(tmp_path):
    path = tmp_path / "message_triggers.json"
    original = b'{"version":1,"triggers":[}'
    path.write_bytes(original)
    store = MessageTriggerStore(path)

    with pytest.raises(ValueError, match="Cannot save"):
        store.save([trigger()])

    assert path.read_bytes() == original
    assert store.list() == ()
    assert not list(tmp_path.glob("*.tmp"))


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

    def message(content, user="viewer-id", outgoing=False):
        return IncomingChatMessage("channel", content, ChatAuthor(user, user), respond, outgoing)

    assert not await dispatcher.dispatch(message("!unknown вась"), services)
    assert not await dispatcher.dispatch(message("вась", "bot-id", outgoing=True), services)
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
