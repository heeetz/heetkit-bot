"""Focused tests for runtime command settings and local overrides."""

import json
import logging

import pytest

from app.errors import UserError

from app.commands.info import register_info_commands
from app.commands.registry import CommandRegistry
from app.runtime_state import RuntimeState
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy
from app.config_file import ConfigFile
from config_helpers import read_section, write_section


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()

    @registry.command(
        "ping",
        required_permission=Permission.MODERATOR,
        cooldown=CooldownPolicy(global_seconds=10.0),
    )
    async def ping(context, arguments: str) -> None:
        return None

    @registry.command("weather")
    async def weather(context, arguments: str) -> None:
        return None

    return registry


@pytest.mark.parametrize(("old", "help_aliases", "expected", "overflow"), [
    ({"removed": True, "aliases": ["catalog"]}, ["guide"], ("guide",), False),
    ({"enabled": False}, ["commands", "guide"], ("guide",), False),
    ({"permission": "MODERATOR", "cooldown": {"global_seconds": 45}}, [], ("commands",), False),
    ({"primary_name": "catalog", "aliases": ["guide", "ping", "help", "taken", "pages"]},
     ["guide"], ("commands", "guide", "catalog", "pages"), False),
    ({"aliases": [f"page{index}" for index in range(10)]}, ["guide"],
     ("commands", "guide", *(f"page{index}" for index in range(8))), True),
])
def test_saved_commands_settings_convert_on_next_write(tmp_path, caplog, old, help_aliases, expected, overflow):
    path = tmp_path / "command_settings.json"
    original = json.dumps({"schema_version": 1, "commands": {
        "commands": old, "help": {"aliases": help_aliases}, "weather": {"aliases": ["taken"]}}})
    path.write_text(original, encoding="utf-8")
    registry = build_registry()
    register_info_commands(registry)
    state = RuntimeState(ConfigFile(path))
    state.configure_commands(registry.definitions())

    help_settings = state.get_command_settings("help")
    assert help_settings.aliases == expected
    assert help_settings.permission == Permission.USER
    assert help_settings.cooldown == state.get_command_default_settings("help").cooldown
    assert state.resolve_command_alias("commands") == ("help" if "commands" in expected else None)
    assert "commands" not in state.runtime_toggleable_commands
    assert ("Dropping 2 aliases" in caplog.text) is overflow
    assert path.read_text(encoding="utf-8") == original

    state.save_command_override("weather")
    assert "commands" not in read_section(path, "commands")
    restarted = RuntimeState(ConfigFile(path))
    restarted.configure_commands(registry.definitions())
    assert restarted.get_command_settings("help") == help_settings


@pytest.mark.parametrize("apply_first", [False, True], ids=["save", "apply-then-save"])
def test_settings_persist_only_on_save_and_reset_clears_override(tmp_path, apply_first):
    path = tmp_path / "command_settings.json"
    definitions = build_registry().definitions()
    state = RuntimeState(ConfigFile(path))
    state.configure_commands(definitions)
    defaults = state.get_command_settings("ping")
    changes = dict(
        enabled=False, permission=Permission.BROADCASTER,
        cooldown=CooldownPolicy(per_user_seconds=1, global_seconds=2),
    )
    if apply_first:
        state.apply_command_settings("ping", **changes)
        assert not state.command_settings_are_saved("ping")
        assert not state.has_saved_command_override("ping")
        assert not path.exists()
        state.save_command_override("ping")
    else:
        state.save_command_settings("ping", **changes)

    saved = state.get_command_settings("ping")
    assert not saved.enabled
    assert saved.permission is changes["permission"] and saved.cooldown == changes["cooldown"]
    assert state.command_settings_are_saved("ping") and state.has_saved_command_override("ping")
    assert list(tmp_path.iterdir()) == [path]
    reopened = RuntimeState(ConfigFile(path))
    reopened.configure_commands(definitions)
    assert reopened.get_command_settings("ping") == saved
    assert reopened.reset_command_settings("ping") == defaults
    assert reopened.command_settings_are_saved("ping") and not reopened.has_saved_command_override("ping")
    assert read_section(path, "commands") == {}


def test_failed_explicit_save_does_not_apply_runtime_change(tmp_path, monkeypatch) -> None:
    runtime_state = RuntimeState(ConfigFile(tmp_path / "command_settings.json"))
    runtime_state.configure_commands(build_registry().definitions())
    original = runtime_state.get_command_settings("ping")

    def fail_save(*args, **kwargs) -> None:
        raise OSError("expected write failure")

    monkeypatch.setattr("app.runtime_state.save_command_overrides", fail_save)

    with pytest.raises(OSError, match="expected write failure"):
        runtime_state.save_command_settings(
            "ping",
            enabled=False,
            cooldown=CooldownPolicy(),
            permission=Permission.USER,
        )

    assert runtime_state.get_command_settings("ping") == original
    assert runtime_state.command_settings_are_saved("ping") is True


def test_partial_and_malformed_values_fall_back_individually(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings_path = tmp_path / "command_settings.json"
    write_section(settings_path, "commands", {
                "stale": {"enabled": False},
                "ping": {
                    "enabled": "false",
                    "cooldown": {
                        "per_user_seconds": 4,
                        "global_seconds": -1,
                    },
                    "permission": "OWNER",
                },
                "weather": {"enabled": False},
            })
    registry = build_registry()

    with caplog.at_level(logging.WARNING):
        runtime_state = RuntimeState(ConfigFile(settings_path))
        runtime_state.configure_commands(registry.definitions())

    ping = runtime_state.get_command_settings("ping")
    assert ping.enabled is True
    assert ping.cooldown == CooldownPolicy(
        per_user_seconds=4.0,
        global_seconds=10.0,
    )
    assert ping.permission is Permission.MODERATOR
    assert runtime_state.get_command_settings("weather").enabled is False
    assert "unknown command" in caplog.text
    assert "invalid enabled" in caplog.text
    assert "invalid permission" in caplog.text
    assert "invalid cooldown" in caplog.text


@pytest.mark.parametrize("file_content", ["", "[]", "{not-json"])
def test_malformed_settings_file_does_not_block_defaults(
    tmp_path,
    file_content: str,
) -> None:
    settings_path = tmp_path / "command_settings.json"
    settings_path.write_text(file_content, encoding="utf-8")
    registry = build_registry()
    runtime_state = RuntimeState(ConfigFile(settings_path))

    runtime_state.configure_commands(registry.definitions())

    assert runtime_state.get_command_settings("ping") == registry.get("ping").default_settings


def test_runtime_operations_reject_invalid_typed_values() -> None:
    runtime_state = RuntimeState()
    runtime_state.configure_commands(build_registry().definitions())

    with pytest.raises(UserError) as error:
        runtime_state.apply_command_settings("ping", enabled="false")  # type: ignore[arg-type]
    assert error.value.code == "command_settings.command_enabled_setting_must_be_a_boolean"
    with pytest.raises(UserError) as error:
        runtime_state.apply_command_settings("ping", permission="MODERATOR")  # type: ignore[arg-type]
    assert error.value.code == "command_settings.command_permission_setting_must_be_a_permission"
    with pytest.raises(UserError) as error:
        runtime_state.apply_command_settings("missing", enabled=False)
    assert error.value.code == "runtime_state.unknown_command"


def test_repeated_settings_reads_reuse_compiled_validators() -> None:
    # Rebuilding a pydantic validator per field made the Commands list take
    # hundreds of milliseconds on the shared event loop.
    from app.settings_models import _adapter

    runtime_state = RuntimeState()
    runtime_state.configure_commands(build_registry().definitions())
    runtime_state.command_settings_are_saved("ping")
    compiled = _adapter.cache_info().misses
    for _ in range(3):
        for name in ("ping", "weather"):
            runtime_state.command_settings_are_saved(name)
    assert _adapter.cache_info().misses == compiled


def test_ai_toggle_preserves_other_saved_commands_and_unsaved_runtime_changes(tmp_path) -> None:
    path = tmp_path / "command_settings.json"
    registry = build_registry()

    @registry.command("ask")
    async def ask(context, arguments: str) -> None:
        return None

    state = RuntimeState(ConfigFile(path))
    state.configure_commands(registry.definitions())
    state.save_command_settings(
        "ping", enabled=False, cooldown=CooldownPolicy(global_seconds=30),
        permission=Permission.VIP,
    )
    saved_ping = read_section(path, "commands")["ping"]
    state.apply_command_settings("ping", enabled=True, permission=Permission.BROADCASTER)
    state.apply_command_settings("weather", enabled=False)

    state.set_ai_enabled(False)

    assert read_section(path, "commands") == {
        "ask": {"enabled": False}, "ping": saved_ping,
    }
    assert state.get_command_settings("ping").enabled is True
    assert state.get_command_settings("ping").permission is Permission.BROADCASTER
    assert state.get_command_settings("weather").enabled is False
    restarted = RuntimeState(ConfigFile(path))
    restarted.configure_commands(registry.definitions())
    assert restarted.ai_enabled is False
    assert restarted.get_command_settings("ping").enabled is False
    assert restarted.get_command_settings("weather").enabled is True
