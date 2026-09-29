"""Focused tests for runtime command settings and local overrides."""

import json
import logging

import pytest

from app.command_settings import save_command_overrides
from app.commands.registry import CommandRegistry
from app.runtime_state import RuntimeState
from app.twitch.permissions import Permission
from app.utils.cooldown import CooldownPolicy


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


def test_settings_derive_from_registry_and_apply_runtime_changes() -> None:
    registry = build_registry()
    runtime_state = RuntimeState()
    runtime_state.configure_commands(registry.definitions())

    defaults = runtime_state.get_command_settings("ping")
    assert defaults.enabled is True
    assert defaults.cooldown == CooldownPolicy(global_seconds=10.0)
    assert defaults.permission is Permission.MODERATOR

    updated = runtime_state.apply_command_settings(
        "ping",
        enabled=False,
        cooldown=CooldownPolicy(per_user_seconds=2.0, global_seconds=3.0),
        permission=Permission.VIP,
    )

    assert updated.enabled is False
    assert updated.cooldown == CooldownPolicy(per_user_seconds=2.0, global_seconds=3.0)
    assert updated.permission is Permission.VIP


def test_saved_override_loads_and_reset_restores_defaults(tmp_path) -> None:
    settings_path = tmp_path / "command_settings.json"
    registry = build_registry()
    runtime_state = RuntimeState(command_settings_path=settings_path)
    runtime_state.configure_commands(registry.definitions())
    runtime_state.apply_command_settings(
        "ping",
        enabled=False,
        cooldown=CooldownPolicy(per_user_seconds=1.0, global_seconds=2.0),
        permission=Permission.BROADCASTER,
    )

    runtime_state.save_command_override("ping")

    saved_payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved_payload == {
        "ping": {
            "cooldown": {"global_seconds": 2.0, "per_user_seconds": 1.0},
            "enabled": False,
            "permission": "BROADCASTER",
        }
    }
    assert list(tmp_path.glob(".command_settings.json.*.tmp")) == []

    restored_state = RuntimeState(command_settings_path=settings_path)
    restored_state.configure_commands(registry.definitions())
    assert restored_state.get_command_settings("ping") == runtime_state.get_command_settings(
        "ping"
    )

    reset_settings = restored_state.reset_command_settings("ping")
    assert reset_settings == registry.get("ping").default_settings
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {}


def test_save_explicit_settings_applies_and_persists_atomically(tmp_path) -> None:
    settings_path = tmp_path / "command_settings.json"
    registry = build_registry()
    runtime_state = RuntimeState(command_settings_path=settings_path)
    runtime_state.configure_commands(registry.definitions())

    saved = runtime_state.save_command_settings(
        "ping",
        enabled=False,
        cooldown=CooldownPolicy(per_user_seconds=6.0, global_seconds=7.0),
        permission=Permission.SUBSCRIBER,
    )

    assert runtime_state.get_command_settings("ping") == saved
    assert runtime_state.command_settings_are_saved("ping") is True
    assert runtime_state.has_saved_command_override("ping") is True
    restored = RuntimeState(command_settings_path=settings_path)
    restored.configure_commands(registry.definitions())
    assert restored.get_command_settings("ping") == saved


def test_apply_is_runtime_only_until_saved_and_reset_clears_override(tmp_path) -> None:
    settings_path = tmp_path / "command_settings.json"
    registry = build_registry()
    runtime_state = RuntimeState(command_settings_path=settings_path)
    runtime_state.configure_commands(registry.definitions())

    runtime_state.apply_command_settings("ping", enabled=False)
    assert runtime_state.command_settings_are_saved("ping") is False
    assert runtime_state.has_saved_command_override("ping") is False

    runtime_state.save_command_override("ping")
    assert runtime_state.command_settings_are_saved("ping") is True
    assert runtime_state.has_saved_command_override("ping") is True

    runtime_state.reset_command_settings("ping")
    assert runtime_state.get_command_settings("ping") == registry.get("ping").default_settings
    assert runtime_state.command_settings_are_saved("ping") is True
    assert runtime_state.has_saved_command_override("ping") is False


def test_failed_explicit_save_does_not_apply_runtime_change(tmp_path, monkeypatch) -> None:
    runtime_state = RuntimeState(command_settings_path=tmp_path / "command_settings.json")
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
    settings_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    registry = build_registry()

    with caplog.at_level(logging.WARNING):
        runtime_state = RuntimeState(command_settings_path=settings_path)
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
    runtime_state = RuntimeState(command_settings_path=settings_path)

    runtime_state.configure_commands(registry.definitions())

    assert runtime_state.get_command_settings("ping") == registry.get("ping").default_settings


def test_runtime_operations_reject_invalid_typed_values() -> None:
    runtime_state = RuntimeState()
    runtime_state.configure_commands(build_registry().definitions())

    with pytest.raises(TypeError, match="boolean"):
        runtime_state.apply_command_settings("ping", enabled="false")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Permission"):
        runtime_state.apply_command_settings("ping", permission="MODERATOR")  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="Unknown command"):
        runtime_state.apply_command_settings("missing", enabled=False)


def test_failed_atomic_write_cleans_up_temporary_file(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "command_settings.json"

    def fail_json_write(*args, **kwargs) -> None:
        raise OSError("expected write failure")

    monkeypatch.setattr("app.command_settings.json.dump", fail_json_write)

    with pytest.raises(OSError, match="expected write failure"):
        save_command_overrides(settings_path, {})

    assert not settings_path.exists()
    assert list(tmp_path.glob(".command_settings.json.*.tmp")) == []
