"""Clean profiles, upgrade persistence, and credential isolation."""

import json
import shutil
import sys
from types import SimpleNamespace

from app.app_settings import AppSettingsStore
from app.commands.fun import FORECASTS, load_fun_settings
from app.config.settings import load_settings_with_credentials
from app.credentials import CredentialName, CredentialStore
from app.runtime_paths import DEFAULT_FILTERS, FILTER_NAMES, RuntimePaths, prepare_runtime_data
from app.runtime_state import RuntimeState
from app import webview_host


def prepare(paths, legacy):
    return prepare_runtime_data(str(legacy / 'tokens.json'), f'sqlite+aiosqlite:///{legacy / "old.db"}',
                                paths=paths, legacy_data=legacy)


def test_clean_profile_never_imports_checkout_state_and_config_reset_preserves_auth_and_db(tmp_path):
    legacy = tmp_path / 'legacy'
    (legacy / 'filters').mkdir(parents=True)
    for filename in ('app_settings.json', 'custom_commands.json', 'message_triggers.json', 'personality_settings.json'):
        (legacy / filename).write_text('private', encoding='utf-8')
    (legacy / 'filters' / FILTER_NAMES[0]).write_text('private rule', encoding='utf-8')
    (legacy / 'tokens.json').write_text('private token', encoding='utf-8')
    (legacy / 'old.db').write_bytes(b'private database')
    paths = RuntimePaths(tmp_path / 'clean')
    prepare(paths, legacy)
    assert not paths.tokens.exists() and not paths.database.exists()
    assert AppSettingsStore(paths.app_settings).snapshot().twitch.presets == ()
    assert RuntimeState(personality_settings_path=paths.personality_settings).available_personalities == ('neutral',)
    assert json.loads(paths.message_triggers.read_text())['triggers'] == []
    for filename in FILTER_NAMES:
        assert (paths.filters / filename).read_bytes() == (DEFAULT_FILTERS / filename).read_bytes()
    paths.tokens.write_bytes(b'kept token')
    paths.database.write_bytes(b'kept database')
    shutil.rmtree(paths.config)
    prepare(paths, legacy)
    assert paths.tokens.read_bytes() == b'kept token'
    assert paths.database.read_bytes() == b'kept database'
    assert json.loads(paths.message_triggers.read_text())['triggers'] == []
    assert not paths.custom_commands.exists()


def test_profile_upgrade_preserves_all_local_files_and_custom_personalities(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / 'profile')
    monkeypatch.setenv('TWITCH_BOT_DATA_DIR', str(paths.root))
    prepare(paths, tmp_path)
    state = RuntimeState(personality_settings_path=paths.personality_settings)
    state.save_ai_personality('my-style', 'User style with {literal braces}')
    files = [paths.app_settings, paths.command_settings, paths.custom_commands, paths.message_triggers,
             paths.config / 'fun_settings.json', *(paths.filters / name for name in FILTER_NAMES)]
    for path in files:
        path.write_text('local data', encoding='utf-8')
    snapshots = {path: path.read_bytes() for path in [*files, paths.personality_settings]}
    prepare(paths, tmp_path)
    assert all(path.read_bytes() == content for path, content in snapshots.items())
    restored = RuntimeState(personality_settings_path=paths.personality_settings)
    assert restored.active_ai_personality == 'my-style'
    assert restored.get_ai_personality_prompt('my-style') == 'User style with {literal braces}'
    assert restored.available_personalities == ('neutral', 'my-style')
    from config import build_ai_system_instruction
    assert 'User style' in build_ai_system_instruction('my-style', restored.get_ai_personality_prompt('my-style'))


def test_keyring_namespaces_are_independent_and_config_reset_leaves_credentials(tmp_path, monkeypatch):
    values = {}
    backend = SimpleNamespace(
        get_password=lambda service, name: values.get((service, name)),
        set_password=lambda service, name, value: values.__setitem__((service, name), value),
    )
    monkeypatch.setenv('TWITCH_BOT_DATA_DIR', str(tmp_path / 'one'))
    one = CredentialStore(backend)
    one.replace(CredentialName.GEMINI_API_KEY, 'one-key')
    monkeypatch.setenv('TWITCH_BOT_DATA_DIR', str(tmp_path / 'two'))
    two = CredentialStore(backend)
    assert two.get(CredentialName.GEMINI_API_KEY) is None
    two.replace(CredentialName.GEMINI_API_KEY, 'two-key')
    assert one.get(CredentialName.GEMINI_API_KEY) == 'one-key'
    assert two.get(CredentialName.GEMINI_API_KEY) == 'two-key'


def test_cli_profile_is_resolved_before_checks_without_creating_it(tmp_path, monkeypatch):
    root = tmp_path / 'clean'
    monkeypatch.setenv('TWITCH_BOT_DATA_DIR', str(tmp_path / 'other'))
    monkeypatch.setattr(sys, 'argv', ['twitch-bot', '--data-dir', str(root), '--check', '--dev-url', 'http://localhost:5173'])
    def load():
        assert RuntimePaths.default().root == root
        return SimpleNamespace(log_level='INFO'), None
    monkeypatch.setattr(webview_host, 'load_settings_with_credentials', load)
    monkeypatch.setattr(webview_host, 'configure_logging', lambda level: None)
    webview_host.main()
    assert not root.exists()


def test_alternate_profile_uses_its_env_and_canonical_storage(tmp_path, monkeypatch):
    root = tmp_path / 'clean'
    root.mkdir()
    monkeypatch.setenv('TWITCH_BOT_DATA_DIR', str(root))
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text('TWITCH_BOT_USERNAME=owner\nGEMINI_API_KEY=owner-secret\n', encoding='utf-8')
    (root / '.env').write_text('\n'.join([
        'TWITCH_CLIENT_ID=test', 'TWITCH_CLIENT_SECRET=test', 'TWITCH_BOT_USER_ID=1',
        'TWITCH_BOT_USERNAME=clean', 'TWITCH_CHANNEL_USER_ID=2', 'TWITCH_CHANNEL=clean',
        'DATABASE_URL=sqlite+aiosqlite:///foreign.db', 'TWITCH_TOKEN_FILE=foreign.json',
    ]), encoding='utf-8')
    # Environment values are deliberate overrides; remove any real deployment values here.
    for name in ('TWITCH_CLIENT_ID', 'TWITCH_CLIENT_SECRET', 'TWITCH_BOT_USER_ID', 'TWITCH_BOT_USERNAME',
                 'TWITCH_CHANNEL_USER_ID', 'TWITCH_CHANNEL', 'GEMINI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    store = SimpleNamespace(get=lambda name: None)
    settings, _ = load_settings_with_credentials(store)
    assert settings.twitch_bot_username == 'clean'
    assert settings.gemini_api_key is None
    assert settings.twitch_token_file == str(root / 'auth' / 'twitchio_tokens.json')
    assert settings.database_url.endswith(str(root / 'data' / 'twitch_bot.db'))


def test_fun_responses_are_local_and_neutral_when_missing_or_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv('TWITCH_BOT_DATA_DIR', str(tmp_path))
    assert load_fun_settings()[1] == FORECASTS
    path = tmp_path / 'config' / 'fun_settings.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'version': 1, 'tg_message': 'community link', 'forecasts': ['local forecast']}))
    assert load_fun_settings() == ('community link', ('local forecast',))
    path.write_text('{broken')
    assert load_fun_settings()[1] == FORECASTS
