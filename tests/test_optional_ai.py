"""Optional provider availability never overwrites configured command preferences."""

import asyncio
import logging
from types import SimpleNamespace

import google
import pytest
from keyring.errors import PasswordDeleteError
from pydantic import SecretStr

from app.commands.ai import register_ai_commands
from app.commands.fun import register_fun_commands
from app.commands.registry import CommandDispatcher, CommandRegistry
from app.config.settings import Settings
from app.credentials import CredentialManager, CredentialName, CredentialStore
from app.fun_settings import FunSettingsStore
from app.runtime_state import RuntimeState
from app.services.contracts import AIReply
from app.services.gemini_ai_service import GeminiAIService
from app.twitch.events import ChatAuthor, IncomingChatMessage
from app.utils.cooldown import CooldownManager
from app.webview_host import AsyncioBackendHost, WebUIBridge


def test_gemini_availability_handles_absent_blank_and_missing_provider(monkeypatch):
    settings = Settings(_env_file=None, gemini_api_key=None)
    service = GeminiAIService(settings)
    assert not service.is_available
    settings.gemini_api_key = SecretStr("   ")
    assert not service.is_available
    settings.gemini_api_key = SecretStr("synthetic-test-key")
    assert service.is_available
    monkeypatch.setattr(google, "genai", None)
    assert not service.is_available
    assert asyncio.run(service.generate_reply("question", "user")) == AIReply("", False)


@pytest.mark.parametrize("enabled", [True, False])
def test_clean_backend_provider_changes_restore_availability_and_preserve_saved_state(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("TWITCH_BOT_DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None, gemini_api_key=None, twitch_client_secret=None)
    values = {}
    def remove(service, name):
        if (service, name) not in values:
            raise PasswordDeleteError("missing")
        del values[(service, name)]
    keyring = SimpleNamespace(
        get_password=lambda service, name: values.get((service, name)),
        set_password=lambda service, name, value: values.__setitem__((service, name), value),
        delete_password=remove,
    )
    manager = CredentialManager({name: None for name in CredentialName}, CredentialStore(keyring))
    backend = AsyncioBackendHost(settings)
    try:
        backend.start()
        bridge = WebUIBridge(backend, credential_manager=manager)
        state = backend.application.services.runtime_state
        defaults = state.get_command_default_settings("ask")
        state.save_command_settings("ask", enabled=enabled, cooldown=defaults.cooldown, permission=defaults.permission)
        saved = (tmp_path / "config" / "command_settings.json").read_bytes()
        commands = {item["name"]: item for item in bridge.get_commands()["commands"]}
        assert commands["ask"]["enabled"] is enabled
        assert commands["ask"]["available"] is False
        assert all(item["available"] for name, item in commands.items() if name != "ask")
        assert [name for name, item in commands.items() if item["response_pool"]] == ["forecast"]
        assert bridge.get_ai_status()["available"] is False
        assert bridge.replace_credential("gemini_api_key", "synthetic-test-key") == {"ok": True}
        assert bridge.get_ai_status()["available"] is True
        ask = next(item for item in bridge.get_commands()["commands"] if item["name"] == "ask")
        assert ask["available"] is True and ask["enabled"] is enabled
        assert bridge.remove_credential("gemini_api_key") == {"ok": True, "changed": True}
        assert not bridge.get_ai_status()["available"]
        assert settings.gemini_api_key is None
        assert state.get_command_settings("ask").enabled is enabled
        assert state.command_settings_are_saved("ask")
        assert (tmp_path / "config" / "command_settings.json").read_bytes() == saved
    finally:
        backend.close()


@pytest.mark.asyncio
async def test_unavailable_ai_does_not_consume_cooldown_or_block_normal_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_DATA_DIR", str(tmp_path))
    registry = CommandRegistry()
    register_ai_commands(registry)
    register_fun_commands(registry, FunSettingsStore(tmp_path / "fun_settings.json"))
    state = RuntimeState(command_settings_path=tmp_path / "command_settings.json")
    state.configure_commands(registry.definitions())
    replies = []
    calls = []
    async def respond(text):
        replies.append(text)
    async def generate_reply(**kwargs):
        calls.append(kwargs)
        return AIReply("Synthetic reply", True)
    provider = SimpleNamespace(is_available=False, generate_reply=generate_reply)
    services = SimpleNamespace(ai=provider, runtime_state=state,
                               ai_request_policy=SimpleNamespace(check=lambda _: None))
    dispatcher = CommandDispatcher(registry=registry, runtime_state=state, cooldowns=CooldownManager(),
                                   logger=logging.getLogger("tests.ai"), command_prefix="!")
    def message(content):
        return IncomingChatMessage(channel="test", content=content,
                                   author=ChatAuthor(twitch_user_id="user", username="viewer", is_moderator=True),
                                   respond=respond)
    for unavailable_provider in (None, SimpleNamespace(), provider):
        services.ai = unavailable_provider
        await dispatcher.dispatch(message("!ask question"), services)
    assert not replies and not calls
    await dispatcher.dispatch(message("!ping"), services)
    assert replies == ["pong"]
    provider.is_available = True
    services.ai = provider
    await dispatcher.dispatch(message("!ask question"), services)
    assert len(calls) == 1
    assert replies[-1] == "@viewer Synthetic reply"
    await dispatcher.dispatch(message("!ask another question"), services)
    assert len(calls) == 1
    assert state.get_command_settings("ask").enabled
