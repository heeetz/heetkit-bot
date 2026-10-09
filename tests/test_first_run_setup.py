"""Offline UI setup and process environment/profile compatibility checks."""

import json
import pytest

from app import webview_host
from app.app_settings import AppSettingsStore
from app.config.settings import Settings, load_settings_with_credentials
from app.credentials import CredentialStore
from app.runtime_paths import RuntimePaths, prepare_runtime_data


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, name):
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        self.values[(service, name)] = value

    def delete_password(self, service, name):
        del self.values[(service, name)]


def clear_environment(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("HEETKIT_DATA_DIR", raising=False)
    monkeypatch.delenv("TWITCH_BOT_DATA_DIR", raising=False)  # Legacy compatibility alias.


def test_normal_profile_ignores_all_legacy_dotenv_locations(tmp_path, monkeypatch):
    clear_environment(monkeypatch)
    source = tmp_path / "source"
    profile = tmp_path / "profile"
    unrelated = tmp_path / "unrelated"
    for path in (source, profile, unrelated):
        path.mkdir()
    (source / ".env").write_text("TWITCH_BOT_USERNAME=sourcebot\nTWITCH_CLIENT_SECRET=source-secret\n")
    (profile / ".env").write_text("TWITCH_BOT_USERNAME=profilebot\nTWITCH_CLIENT_SECRET=profile-secret\n")
    (unrelated / ".env").write_text("TWITCH_BOT_USERNAME=foreignbot\nTWITCH_CLIENT_SECRET=foreign-secret\n")
    monkeypatch.setattr("app.runtime_paths.SOURCE_ROOT", source)
    monkeypatch.setattr("app.runtime_paths.user_data_path", lambda *args, **kwargs: profile)
    monkeypatch.chdir(unrelated)
    store = CredentialStore(MemoryKeyring())
    loaded, _ = load_settings_with_credentials(store)
    assert loaded.twitch_bot_username == ""
    assert loaded.twitch_client_secret is None
    # Plain typed construction also cannot accidentally read the working directory.
    assert Settings().twitch_bot_username == ""


def test_clean_profile_setup_restart_and_start_without_checkout_data(tmp_path, monkeypatch):
    clear_environment(monkeypatch)
    paths = RuntimePaths(tmp_path / "profile")
    monkeypatch.setenv("HEETKIT_DATA_DIR", str(paths.root))
    monkeypatch.chdir(tmp_path)
    credential_store = CredentialStore(MemoryKeyring())
    settings, manager = load_settings_with_credentials(credential_store)
    prepare_runtime_data(settings.twitch_token_file, settings.database_url, paths=paths)
    backend = webview_host.AsyncioBackendHost(settings)
    try:
        backend.start()
        store = AppSettingsStore(paths.app_settings)
        bridge = webview_host.WebUIBridge(backend, app_settings=store, credential_manager=manager)
        assert not bridge.start_bot()["ok"]
        result = bridge.update_twitch_settings("#Target", "200", None, "client-id", "NewBot", "100")
        assert result == {"ok": True, "requires_reconnect": True, "requires_restart": True}
        assert bridge.get_twitch_settings()["settings"]["bot_username"] == "newbot"
        assert bridge.reconnect_twitch()["ok"] is False
        assert settings.twitch_bot_username == ""
        assert bridge.replace_credential("twitch_client_secret", "synthetic-secret")["ok"]
        assert bridge.replace_credential("gemini_api_key", "synthetic-gemini")["ok"]
        assert bridge.update_ai_provider_settings("gemini-ui-selected", "gemini-ui-fallback")["ok"]
        assert backend.application.settings.gemini_api_key.get_secret_value() == "synthetic-gemini"
    finally:
        backend.close()

    payload = json.loads(paths.app_settings.read_text())
    assert payload["twitch"]["client_id"] == "client-id"
    assert "synthetic-secret" not in paths.app_settings.read_text()
    assert "synthetic-gemini" not in paths.app_settings.read_text()
    assert not paths.tokens.exists()
    restarted, _ = load_settings_with_credentials(credential_store)
    saved = AppSettingsStore(paths.app_settings).snapshot()
    restarted = webview_host.apply_twitch_app_settings(restarted, saved)
    restarted = webview_host.apply_ai_app_settings(restarted, saved)
    restarted.validate_twitch_configuration()
    assert restarted.twitch_bot_username == "newbot"
    assert restarted.twitch_client_secret.get_secret_value() == "synthetic-secret"
    assert restarted.gemini_api_key.get_secret_value() == "synthetic-gemini"
    assert (restarted.gemini_model, restarted.gemini_fallback_model) == ("gemini-ui-selected", "gemini-ui-fallback")
    assert restarted.twitch_token_file == str(paths.tokens)
    assert restarted.database_url.endswith(str(paths.database))

    # Verify the real session boundary receives the configured profile, offline.
    calls = []
    async def fake_twitch(**kwargs):
        calls.append(kwargs["settings"].primary_account)
        await kwargs["stop_event"].wait()
    monkeypatch.setattr("app.bot_runtime.run_twitch_bot", fake_twitch)
    backend = webview_host.AsyncioBackendHost(restarted)
    try:
        backend.start()
        bridge = webview_host.WebUIBridge(backend, app_settings=AppSettingsStore(paths.app_settings))
        assert bridge.get_twitch_settings()["settings"]["requires_restart"] is False
        assert bridge.start_bot()["ok"]
        assert bridge.stop_bot()["ok"]
        assert len(calls) == 1 and calls[0].username == "newbot"
        assert calls[0].channel == "target"
    finally:
        backend.close()
    assert not list(tmp_path.rglob(".env"))


@pytest.mark.parametrize("identity", [
    ("", "bot", "100"), ("client-id", "bad login", "100"),
    ("client-id", "bot", "not-numeric"), ("client-id", None, None),
])
def test_invalid_setup_never_saves_a_partial_target_or_identity(tmp_path, identity):
    path = tmp_path / "app_settings.json"
    store = AppSettingsStore(path)
    before = store.snapshot()
    with pytest.raises(ValueError):
        store.update_twitch(channel="target", channel_user_id="200", client_id=identity[0],
                            bot_username=identity[1], bot_user_id=identity[2])
    assert store.snapshot() == before
    assert not path.exists()


def test_target_presets_and_unrelated_saves_preserve_identity(tmp_path):
    path = tmp_path / "app_settings.json"
    store = AppSettingsStore(path)
    store.update_twitch(channel="target", channel_user_id="200", client_id="client-id",
                        bot_username="Bot", bot_user_id="100")
    _, preset = store.save_twitch_preset(display_name="Another channel", channel="another", channel_user_id="300")
    store.delete_twitch_preset(preset.id)
    store.update_twitch(channel="target", channel_user_id="200")
    store.update_ai_memory(enabled=False)
    saved = AppSettingsStore(path).snapshot().twitch
    assert (saved.client_id, saved.bot_username, saved.bot_user_id) == ("client-id", "bot", "100")


def test_legacy_target_only_settings_preserve_deployment_identity(tmp_path):
    path = tmp_path / "app_settings.json"
    path.write_text(json.dumps({"version": 1, "twitch": {"channel": "target", "channel_user_id": "200"}}))
    settings = Settings(_env_file=None, twitch_client_id="legacy-client", twitch_bot_username="legacybot", twitch_bot_user_id="100")
    applied = webview_host.apply_twitch_app_settings(settings, AppSettingsStore(path).snapshot())
    assert applied.twitch_client_id == "legacy-client"
    assert applied.twitch_bot_username == "legacybot"
    assert applied.twitch_channel == "target"


def test_existing_owner_profile_and_keyring_survive_without_legacy_files(tmp_path, monkeypatch):
    clear_environment(monkeypatch)
    monkeypatch.setattr("app.runtime_paths.user_data_path", lambda *args, **kwargs: tmp_path)
    paths = RuntimePaths.default()
    paths.config.mkdir()
    # Existing v1 and domain-store formats, with no new format requirement.
    paths.app_settings.write_text(json.dumps({
        "version": 1, "window": {"close_to_tray": True},
        "ai": {"memory_enabled": False, "selected_model": "gemini-owner",
               "fallback_model": "gemini-owner-fallback", "cooldown_bypass_user_id": "123"},
        "twitch": {"client_id": "saved-client", "bot_username": "savedbot", "bot_user_id": "100",
                   "channel": "savedtarget", "channel_user_id": "200"},
    }), encoding="utf-8")
    paths.personality_settings.write_text(json.dumps({
        "active_personality": "local-style", "overrides": {"local-style": "Private local style"},
    }), encoding="utf-8")
    paths.command_settings.write_text(json.dumps({"ask": {"enabled": False}}), encoding="utf-8")
    fun_path = paths.config / "fun_settings.json"
    fun_path.write_text(json.dumps({"version": 1, "tg_message": "Local link", "forecasts": ["Local forecast"]}), encoding="utf-8")
    before = {path: path.read_bytes() for path in paths.config.iterdir()}
    monkeypatch.setenv("TWITCH_BOT_USERNAME", "processbot")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-process")
    monkeypatch.setenv("AI_COOLDOWN_BYPASS_USER_ID", "999")
    keyring = MemoryKeyring()
    # Legacy compatibility fixture: former unscoped keyring service.
    keyring.values = {("twitch-bot", "twitch_client_secret"): "synthetic-owner-secret",
                      ("twitch-bot", "gemini_api_key"): "synthetic-owner-key"}
    settings, manager = load_settings_with_credentials(CredentialStore(keyring))
    app_settings = AppSettingsStore(paths.app_settings).snapshot()
    settings = webview_host.apply_twitch_app_settings(settings, app_settings)
    settings = webview_host.apply_ai_app_settings(settings, app_settings)
    settings.validate_twitch_configuration()
    assert settings.twitch_bot_username == "savedbot"
    assert settings.gemini_model == "gemini-owner"
    assert settings.ai_cooldown_bypass_user_id == "123"
    assert all(status.source == "credential_store" for status in manager.statuses())
    backend = webview_host.AsyncioBackendHost(settings, initial_ai_memory_enabled=app_settings.ai.memory_enabled)
    try:
        backend.start()
        bridge = webview_host.WebUIBridge(backend, app_settings=AppSettingsStore(paths.app_settings), credential_manager=manager)
        state = backend.application.services.runtime_state
        assert state.active_ai_personality == "local-style"
        assert state.get_ai_personality_prompt("local-style") == "Private local style"
        assert bridge.get_ai_status()["memory_enabled"] is False
        assert state.get_command_settings("ask").enabled is False
    finally:
        backend.close()
    assert all(path.read_bytes() == content for path, content in before.items() if path != fun_path)
    assert json.loads(fun_path.read_text(encoding="utf-8")) == {
        "version": 1, "tg_message": "Local link", "fates": ["Local forecast"],
    }
    copies = list(paths.config.glob("fun_settings.json.*.recovery"))
    assert len(copies) == 1 and copies[0].read_bytes() == before[fun_path]
    assert not list(tmp_path.rglob(".env"))


def test_profile_cooldown_exception_is_preserved_on_unrelated_saves(tmp_path):
    path = tmp_path / "app_settings.json"
    path.write_text(json.dumps({"version": 1, "ai": {"cooldown_bypass_user_id": "123"}}))
    store = AppSettingsStore(path)
    store.update_ai_memory(enabled=False)
    store.update_ai_models(selected_model="gemini-new", fallback_model="gemini-safe")
    store.update_desktop(start_minimized=False, minimize_to_tray=False, close_to_tray=False, auto_start_bot=False)
    saved = AppSettingsStore(path).snapshot()
    assert saved.ai.cooldown_bypass_user_id == "123"
    settings = webview_host.apply_ai_app_settings(Settings(_env_file=None), saved)
    assert settings.ai_cooldown_bypass_user_id == "123"


@pytest.mark.parametrize("value", ["", " ", "abc", 123, "12 34"])
def test_invalid_profile_cooldown_exception_is_ignored(tmp_path, value):
    path = tmp_path / "app_settings.json"
    path.write_text(json.dumps({"version": 1, "ai": {"cooldown_bypass_user_id": value}}))
    assert AppSettingsStore(path).snapshot().ai.cooldown_bypass_user_id is None
