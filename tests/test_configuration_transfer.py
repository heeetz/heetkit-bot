"""Portable Desktop/Server compatibility and hostile input, without live accounts."""

import base64
import io
import json
import os
import stat
import zipfile
from concurrent.futures import Future

import pytest

from app.app_settings import AppSettingsStore
from app.configuration_transfer import (
    ConfigurationTransfer, MAX_ARCHIVE, MAX_CONFIGURATION, pack_configuration, unpack_configuration,
)
from app.config.settings import Settings
from app.container import build_application
from app.filter_settings import apply_filter_settings, validate_filter_input
from app.management import ApplicationManagement
from app.runtime_paths import FILTER_NAMES
from app.webview_host import FRONTEND_OPERATIONS, WebUIBridge


@pytest.fixture
async def profiles(tmp_path, monkeypatch):
    applications = []

    def create(name):
        root = tmp_path / name
        monkeypatch.setenv("HEETKIT_DATA_DIR", str(root))
        for field in Settings.model_fields:
            monkeypatch.delenv(field.upper(), raising=False)
        config = root / "config"
        (config / "filters").mkdir(parents=True)
        for filename in FILTER_NAMES:
            (config / "filters" / filename).write_text("", encoding="utf-8")
        settings = Settings(twitch_client_secret="secret-client-sentinel", gemini_api_key="secret-gemini-sentinel",
                            twitch_bot_username="syntheticbot", twitch_bot_user_id="100", twitch_channel="syntheticchannel",
                            twitch_channel_user_id="200", twitch_client_id="syntheticclient",
                            twitch_token_file=str(root / "auth" / "tokens.json"),
                            database_url="sqlite+aiosqlite:///" + str(root / "history.db"))
        application = build_application(settings)
        applications.append(application)
        store = AppSettingsStore(config / "app_settings.json")
        return ConfigurationTransfer(application, store)

    async def no_network(*args, **kwargs):
        raise AssertionError("External network is forbidden")

    monkeypatch.setattr("httpx.AsyncClient.send", no_network)
    yield create
    for app in applications:
        await app.shutdown()


async def test_setup_transfer_preserves_nonsecrets_and_requires_destination_routing_consent(profiles):
    from dataclasses import asdict
    from app.config.ai_setup import AIModelSelection, AISetup
    from app.config.profile_settings import apply_ai_app_settings
    source, target = profiles("source-setup"), profiles("destination-setup")
    setup = AISetup(AIModelSelection("deepseek", "deepseek-v4-pro", "high", True),
                    AIModelSelection("gemini", "gemini-2.5-flash", "off", True),
                    cross_provider_acknowledged=True, shared_instructions="Custom shared", max_answer_length=400)
    source.settings.update_ai_setup(asdict(setup))
    source.app.settings.ai_setup = setup
    source.app.settings.ai_provider = "deepseek"
    encoded = source.export()["archive_base64"]
    preview = target.preview(encoded)
    assert "acknowledged" in str(preview["sections"])
    assert "Primary: deepseek / deepseek-v4-pro; thinking high; search on" in str(preview["sections"])
    target.apply(encoded, preview["preview_token"], True)
    saved = AppSettingsStore(target.settings._path).snapshot().ai.setup
    assert saved.primary == setup.primary and saved.fallback == setup.fallback
    assert saved.shared_instructions == "Custom shared" and saved.max_answer_length == 400
    assert not saved.cross_provider_acknowledged
    assert target.app.settings.ai_setup == saved
    # Consent is deliberately absent after restart, too.
    reloaded = apply_ai_app_settings(Settings(), AppSettingsStore(target.settings._path).snapshot())
    assert not reloaded.ai_setup.cross_provider_acknowledged


def seed(transfer):
    state = transfer.state
    state.apply_command_settings("fate", aliases=["destiny"], display_name="Destiny", enabled=False)
    state.create_ai_personality("Portable", "Be concise.")
    state.apply_ai_personality("Portable", "Use a friendly style.")
    state.apply_profile_instructions("Profile instructions.")
    transfer.custom.save({"name": "hello", "enabled": True, "responses": ["Hi {sender}!"],
                          "permission": "USER", "per_user_seconds": 2, "global_seconds": 1,
                          "aliases": ["greeting"]})
    transfer.fun.apply(["Portable fate"], "fate")
    transfer.fun.apply(["Portable Tg"], "tg")
    transfer.blocks.block("blocked_viewer", "12345")
    transfer.triggers.save([{"id": "hello", "enabled": True, "match_mode": "exact", "text": "hello",
                            "case_sensitive": False, "probability": 1, "cooldown_seconds": 5,
                            "responses": ["Welcome"]}])
    apply_filter_settings(transfer.app.services.filter_manager, validate_filter_input({
        "words": ["blockedword"], "phrases": ["blocked phrase"], "patterns": [r"danger\d+"]}))
    state.set_ai_memory_enabled(False)


def file_state(transfer):
    return {path: path.read_bytes() if path.exists() else None for path in transfer.paths()}


async def test_both_provider_choices_transfer_without_credentials_and_legacy_stays_gemini(profiles):
    from app.config.profile_settings import apply_ai_app_settings
    source, target = profiles("source-providers"), profiles("target-providers")
    management = ApplicationManagement(source.app, source.settings)
    await management._save_ai_provider_models("gemini-custom", "gemini-backup")
    await management._save_ai_provider_models("deepseek-custom", "deepseek-backup", "deepseek")
    source.app.settings.deepseek_api_key = "PRIVATE-DEEPSEEK-KEY"
    target.app.settings.deepseek_api_key = "PRIVATE-DESTINATION-KEY"
    encoded = source.export()["archive_base64"]
    payload, _, _ = unpack_configuration(encoded)
    assert "PRIVATE" not in json.dumps(payload)
    target.apply(encoded, target.preview(encoded)["preview_token"], True)
    reloaded = apply_ai_app_settings(Settings(), AppSettingsStore(target.settings._path).snapshot())
    assert reloaded.ai_provider == "deepseek" and reloaded.deepseek_model == "deepseek-custom"
    assert reloaded.gemini_model == "gemini-custom"
    assert target.app.settings.deepseek_api_key == "PRIVATE-DESTINATION-KEY"
    for field in ("provider", "deepseek_selected_model", "deepseek_fallback_model"):
        payload["ai"].pop(field)
    legacy = pack_configuration(payload)
    target.apply(legacy, target.preview(legacy)["preview_token"], True)
    assert target.app.settings.ai_provider == "gemini"
    assert target.app.settings.gemini_model == "gemini-custom"
    assert target.app.settings.deepseek_model == "deepseek-custom"
    payload["ai"]["selected_model"] = "deepseek-flash"
    with pytest.raises(ValueError):
        target.preview(pack_configuration(payload))


async def test_desktop_export_server_preview_import_round_trip_and_restart(profiles):
    source = profiles("desktop")
    seed(source)
    # Exercise the actual desktop adapter: submit the shared coroutine through a
    # synthetic host, without opening a window or accessing keyrings/accounts.
    def submit(coroutine):
        future = Future()
        try:
            coroutine.send(None)
        except StopIteration as completed:
            future.set_result(completed.value)
        return future

    bridge = WebUIBridge(type("Host", (), {"application": source.app, "submit": staticmethod(submit)})(), app_settings=source.settings)
    random_responses = [f"Random reply {index} to {{sender}}" for index in range(30)]
    assert bridge.save_custom_command({
        "name": "randompool", "enabled": True, "response_mode": "random", "responses": random_responses,
        "permission": "USER", "per_user_seconds": 0, "global_seconds": 0, "aliases": [],
    }) == {"ok": True}
    destination = source.config.parent / "portable.zip"
    bridge._window = type("Window", (), {"create_file_dialog": lambda *args, **kwargs: (str(destination),)})()
    exported = bridge.export_configuration()
    assert exported == {"ok": True, "saved": True}
    assert all(name in FRONTEND_OPERATIONS for name in (
        "export_configuration", "preview_configuration_import", "apply_configuration_import"))
    assert bridge._backend.application is source.app
    encoded = base64.b64encode(destination.read_bytes()).decode()
    payload, manifest, _ = unpack_configuration(encoded)
    assert manifest["format_version"] == 1
    assert payload["commands"]["fate"]["aliases"] == ["destiny"]
    assert next(item for item in payload["custom_commands"] if item["name"] == "randompool")["responses"] == random_responses
    assert "secret-client-sentinel" not in json.dumps(payload)
    assert "secret-gemini-sentinel" not in json.dumps(payload)
    assert "twitch" not in payload and "window" not in payload
    target = profiles("server")
    target.settings.update_desktop(start_minimized=True, minimize_to_tray=True, close_to_tray=True, auto_start_bot=True)
    target.settings.update_operation_mode("disabled")
    target.settings.update_twitch(channel="keepchannel", channel_user_id="888")
    target.app.settings.gemini_api_key = "destination-secret"
    extra = json.loads(target.settings._path.read_text())
    extra["future_unrelated"] = {"keep": True}
    target.settings._path.write_text(json.dumps(extra), encoding="utf-8")
    target.settings._path.parent.parent.joinpath("history.db").write_bytes(b"private history sentinel")
    target.settings._path.parent.parent.joinpath("auth").mkdir()
    tokens = target.settings._path.parent.parent / "auth" / "tokens.json"
    tokens.write_bytes(b"private OAuth sentinel")
    before = file_state(target)
    preview = target.preview(encoded)
    assert file_state(target) == before
    assert not (target.config / "import-backups").exists()
    assert len(preview["sections"]) == 8 and preview["preserved"] and preview["effects"]
    server = ApplicationManagement(target.app, target.settings)
    server._configuration_transfer = target
    result = await server.apply_configuration_import(encoded, preview["preview_token"], True)
    assert result["ok"]
    assert target.snapshot() == source.snapshot()
    assert target.settings.snapshot().twitch.channel == "keepchannel"
    assert target.settings.snapshot().startup.auto_start_bot
    assert target.settings.snapshot().startup.operation_mode == "disabled"
    assert target.settings.snapshot().window.start_minimized
    assert json.loads(target.settings._path.read_text())["future_unrelated"] == {"keep": True}
    assert target.app.settings.gemini_api_key == "destination-secret"
    assert tokens.read_bytes() == b"private OAuth sentinel"
    assert tokens.parent.parent.joinpath("history.db").read_bytes() == b"private history sentinel"
    assert target.blocks.is_blocked("12345", "renamed")
    assert target.custom.get_by_name("greeting").name == "hello"
    assert not target.app.services.filter_manager.evaluate_message("blockedword").allowed
    backup = next((target.config / "import-backups").iterdir())
    record = json.loads((backup / "manifest.json").read_text())
    assert len(record["files"]) == len(before)
    for item, (path, data) in zip(record["files"], before.items()):
        assert item["path"] == path.relative_to(target.config).as_posix()
        if data is not None:
            assert (backup / item["backup"]).read_bytes() == data
    # The canonical existing stores reload the same saved state.
    replacement = build_application(target.app.settings)
    try:
        assert replacement.custom_commands.get_by_name("greeting").responses == ("Hi {sender}!",)
        assert replacement.custom_commands.get_by_name("randompool").responses == tuple(random_responses)
        assert replacement.custom_commands.get_by_name("randompool").response_mode == "random"
        assert replacement.services.runtime_state.active_ai_personality == "Portable"
        assert replacement.services.runtime_state.profile_instructions == "Profile instructions."
        assert replacement.services.runtime_state.get_command_settings("fate").aliases == ("destiny",)
        assert replacement.services.ai_user_blocks.is_blocked("12345", "renamed")
        assert replacement.dispatcher._message_triggers.list()[0].id == "hello"
        assert not AppSettingsStore(target.settings._path).snapshot().ai.memory_enabled
    finally:
        await replacement.shutdown()
    # Reverse transport uses the same format too.
    assert unpack_configuration(target.export()["archive_base64"])[0] == payload


async def test_import_rejects_thirty_one_random_templates_without_writes(profiles):
    transfer = profiles("profile")
    seed(transfer)
    payload, _, _ = unpack_configuration(transfer.export()["archive_base64"])
    payload["custom_commands"][0].update(response_mode="random", responses=[f"Reply {index}" for index in range(31)])
    before = file_state(transfer)
    snapshot = transfer.snapshot()
    with pytest.raises(ValueError, match="1 to 30 response templates"):
        transfer.preview(pack_configuration(payload))
    assert file_state(transfer) == before
    assert transfer.snapshot() == snapshot
    assert not (transfer.config / "import-backups").exists()


@pytest.mark.parametrize("change", ["unconfirmed", "wrong_zip", "state_changed", "disk_changed", "expired", "replay"])
async def test_confirmation_is_bound_to_archive_and_destination(profiles, change):
    transfer = profiles("profile")
    encoded = transfer.export()["archive_base64"]
    preview = transfer.preview(encoded)
    token = preview["preview_token"]
    if change == "wrong_zip":
        payload, _, _ = unpack_configuration(encoded)
        payload["ai"]["memory_enabled"] = not payload["ai"]["memory_enabled"]
        encoded = pack_configuration(payload)
    elif change == "state_changed":
        transfer.state.apply_profile_instructions("Changed since preview")
    elif change == "disk_changed":
        transfer.fun.path.write_text('{"version":1,"fates":["External edit"]}')
    elif change == "expired":
        _, digest, fingerprint = transfer.pending[token]
        transfer.pending[token] = (0, digest, fingerprint)
    elif change == "replay":
        transfer.apply(encoded, token, True)
    before = file_state(transfer)
    with pytest.raises(ValueError):
        transfer.apply(encoded, token, change != "unconfirmed")
    assert file_state(transfer) == before


def zip_bytes(entries, compression=zipfile.ZIP_STORED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize("kind", ["traversal", "absolute", "backslash", "duplicate", "unexpected", "symlink",
                                        "directory", "bomb", "oversized", "corrupt", "bad_base64", "bad_manifest",
                                        "wrong_version", "duplicate_json", "nan", "bad_hash"])
async def test_hostile_archives_are_rejected_without_writes(profiles, kind):
    transfer = profiles("profile")
    good = transfer.export()["archive_base64"]
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(good))) as archive:
        manifest = archive.read("manifest.json")
        config = archive.read("configuration.json")
    entries = [("manifest.json", manifest), ("configuration.json", config)]
    if kind in ("traversal", "absolute", "backslash", "unexpected"):
        entries[1] = ({"traversal": "../configuration.json", "absolute": "/configuration.json",
                       "backslash": "..\\configuration.json", "unexpected": "auth/tokens.json"}[kind], config)
    elif kind == "duplicate":
        entries.append(entries[1])
    elif kind in ("symlink", "directory"):
        info = zipfile.ZipInfo("configuration.json")
        info.create_system = 3
        info.external_attr = ((stat.S_IFLNK if kind == "symlink" else stat.S_IFDIR) | 0o777) << 16
        entries[1] = (info, config)
    elif kind == "bomb":
        entries[1] = ("configuration.json", b"x" * MAX_CONFIGURATION)
    elif kind == "oversized":
        entries[1] = ("configuration.json", b"x" * (MAX_ARCHIVE + 1))
    elif kind in ("wrong_version", "bad_hash"):
        value = json.loads(manifest)
        if kind == "wrong_version":
            value["format_version"] = 999
        else:
            value["files"]["configuration.json"]["sha256"] = "0" * 64
        entries[0] = ("manifest.json", json.dumps(value))
    elif kind in ("bad_manifest", "duplicate_json", "nan"):
        entries[0] = ("manifest.json", {"bad_manifest": "[]", "duplicate_json": '{"format":1,"format":2}',
                                       "nan": '{"format":NaN}'}[kind])
    encoded = zip_bytes(entries, zipfile.ZIP_DEFLATED if kind == "bomb" else zipfile.ZIP_STORED)
    if kind == "corrupt":
        encoded = base64.b64encode(b"not a ZIP").decode()
    elif kind == "bad_base64":
        encoded = "***"
    before = file_state(transfer)
    with pytest.raises(ValueError):
        transfer.preview(encoded)
    assert file_state(transfer) == before
    assert not (transfer.config / "import-backups").exists()


@pytest.mark.parametrize("change", ["permission_floor", "protected_alias", "collision", "custom_collision", "invalid_template",
    "unknown_field", "invalid_bool", "invalid_language", "invalid_models", "bad_regex", "unknown_personality",
    "duplicate_personality", "duplicate_block", "invalid_id", "duplicate_trigger"])
async def test_domain_security_and_regression_validation(profiles, change):
    transfer = profiles("profile")
    seed(transfer)
    payload, _, _ = unpack_configuration(transfer.export()["archive_base64"])
    if change == "permission_floor":
        payload["commands"]["erase"]["permission"] = "USER"
    elif change == "protected_alias":
        payload["commands"]["ask"]["aliases"] = ["unsafe"]
    elif change == "collision":
        payload["commands"]["fate"]["aliases"] = ["ask"]
    elif change == "custom_collision":
        payload["custom_commands"][0]["name"] = "fate"
    elif change == "invalid_template":
        payload["custom_commands"][0]["responses"] = ["{__import__}"]
    elif change == "unknown_field":
        payload["api_key"] = "must not import"
    elif change == "invalid_bool":
        payload["ai"]["memory_enabled"] = 1
    elif change == "invalid_language":
        payload["ai"]["response_language"]["mode"] = "untrusted"
    elif change == "invalid_models":
        payload["ai"]["selected_model"] = "../../model"
    elif change == "bad_regex":
        payload["filters"]["patterns"] = ["["]
    elif change == "unknown_personality":
        payload["personalities"]["active_personality"] = "Missing"
    elif change == "duplicate_personality":
        payload["personalities"]["overrides"]["PORTABLE"] = "conflict"
    elif change == "duplicate_block":
        payload["blocked_users"].append(payload["blocked_users"][0])
    elif change == "invalid_id":
        payload["blocked_users"][0]["twitch_user_id"] = "not an ID"
    elif change == "duplicate_trigger":
        payload["triggers"].append(payload["triggers"][0])
    before = file_state(transfer)
    with pytest.raises((ValueError, TypeError)):
        transfer.preview(pack_configuration(payload))
    assert file_state(transfer) == before


@pytest.mark.parametrize("failure", ["backup", "stage", "replace", "publish"])
async def test_failure_restores_disk_and_unsaved_runtime_exactly(profiles, failure, monkeypatch):
    source = profiles("source")
    seed(source)
    target = profiles("target")
    target.state.apply_profile_instructions("Keep unsaved destination")
    target.fun.apply(["Keep unsaved fate"], "fate")
    before = file_state(target)
    active = target.snapshot()
    encoded = source.export()["archive_base64"]
    token = target.preview(encoded)["preview_token"]
    if failure == "publish":
        original_publish = target.publish

        def fail_after_publication(*args):
            original_publish(*args)
            raise OSError("synthetic publication failure")

        monkeypatch.setattr(target, "publish", fail_after_publication)
    elif failure in ("backup", "stage"):
        monkeypatch.setattr(target, {"backup": "write_new", "stage": "stage", "publish": "publish"}[failure],
                            lambda *args: (_ for _ in ()).throw(OSError("synthetic failure")))
    else:
        original = os.replace
        count = 0

        def fail_once(source, destination):
            nonlocal count
            count += 1
            if count == 4:
                raise OSError("synthetic replacement failure")
            return original(source, destination)

        monkeypatch.setattr("app.configuration_transfer.os.replace", fail_once)
    with pytest.raises(OSError):
        target.apply(encoded, token, True)
    assert file_state(target) == before
    assert target.snapshot() == active
    assert not list(target.config.rglob(".configuration-*"))


async def test_future_or_corrupt_destination_refuses_overwrite(profiles):
    transfer = profiles("profile")
    encoded = transfer.export()["archive_base64"]
    for contents in ('{"version":999}', 'corrupt JSON'):
        transfer.settings._path.write_text(contents)
        token = transfer.preview(encoded)["preview_token"]
        before = file_state(transfer)
        with pytest.raises((ValueError, TypeError)):
            transfer.apply(encoded, token, True)
        assert file_state(transfer) == before


async def test_symlink_destination_is_rejected(profiles, tmp_path):
    transfer = profiles("profile")
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    try:
        transfer.custom._path.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    with pytest.raises(ValueError):
        transfer.preview(transfer.export()["archive_base64"])
    assert outside.read_text() == "{}"


@pytest.mark.parametrize("value", ["\\ud800", "\\udfff"])
async def test_invalid_unicode_is_rejected_before_writes(profiles, value):
    transfer = profiles("profile")
    payload, _, _ = unpack_configuration(transfer.export()["archive_base64"])
    payload["personalities"]["profile_instructions"] = json.loads('"' + value + '"')
    before = file_state(transfer)
    with pytest.raises(ValueError):
        transfer.preview(pack_configuration(payload))
    assert file_state(transfer) == before


async def test_deflated_compatible_archive_and_saved_edit_after_import(profiles):
    source = profiles("source")
    seed(source)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(source.export()["archive_base64"]))) as archive:
        encoded = zip_bytes([(name, archive.read(name)) for name in archive.namelist()], zipfile.ZIP_DEFLATED)
    target = profiles("target")
    token = target.preview(encoded)["preview_token"]
    target.apply(encoded, token, True)
    # Imported collections continue to use ordinary edits/persistence, including
    # aliases, permission floors and custom command IDs; no parallel store exists.
    target.custom.save({**target.custom.list()[0].to_json(), "responses": ["Edited {sender}"]})
    target.state.save_ai_personality("Portable", "Edited style")
    target.state.set_ai_enabled(False)
    assert target.custom.get_by_name("hello").responses == ("Edited {sender}",)
    assert target.state.get_ai_personality_prompt("Portable") == "Edited style"
    assert not target.state.ai_enabled


async def test_rollback_storage_failure_retains_exact_original_backups(profiles, monkeypatch):
    source = profiles("source")
    seed(source)
    target = profiles("target")
    target.fun.save(["Destination fate"], "fate")
    before = file_state(target)
    encoded = source.export()["archive_base64"]
    token = target.preview(encoded)["preview_token"]
    original = os.replace
    count = 0

    def fail_from_fifth(source, destination):
        nonlocal count
        count += 1
        if count >= 5:
            raise OSError("persistent storage failure")
        return original(source, destination)

    monkeypatch.setattr("app.configuration_transfer.os.replace", fail_from_fifth)
    with pytest.raises(OSError, match="rollback needs recovery"):
        target.apply(encoded, token, True)
    backup = next((target.config / "import-backups").iterdir())
    record = json.loads((backup / "manifest.json").read_text())
    for item, data in zip(record["files"], before.values()):
        if data is not None:
            assert (backup / item["backup"]).read_bytes() == data


async def test_unrelated_fun_and_app_policy_fields_are_preserved(profiles):
    transfer = profiles("profile")
    transfer.settings.update_ai_memory(enabled=True)
    existing = json.loads(transfer.settings._path.read_text())
    existing["ai"]["cooldown_bypass_user_id"] = "999"
    transfer.settings._path.write_text(json.dumps(existing))
    transfer.settings = AppSettingsStore(transfer.settings._path)
    transfer.fun.path.write_text('{"version":1,"future_option":"keep"}')
    encoded = transfer.export()["archive_base64"]
    token = transfer.preview(encoded)["preview_token"]
    transfer.apply(encoded, token, True)
    assert json.loads(transfer.fun.path.read_text())["future_option"] == "keep"
    assert transfer.settings.snapshot().ai.cooldown_bypass_user_id == "999"
    assert json.loads(transfer.settings._path.read_text())["ai"]["cooldown_bypass_user_id"] == "999"


@pytest.mark.parametrize("case", ["cancel", "missing_window", "invalid_extension", "write_failure"])
async def test_native_export_cancel_and_errors_preserve_destination(profiles, monkeypatch, case):
    import webview

    transfer = profiles("desktop")
    destination = transfer.config.parent / "portable.zip"
    destination.write_bytes(b"existing destination")
    bridge = WebUIBridge(type("Host", (), {"application": transfer.app})(), app_settings=transfer.settings)
    monkeypatch.setattr(bridge, "_configuration_bridge_action", lambda *args: transfer.export())
    dialogs = []

    def dialog(*args, **kwargs):
        dialogs.append((args, kwargs))
        return None if case == "cancel" else (str(destination if case != "invalid_extension" else destination.with_suffix(".json")),)

    if case != "missing_window":
        bridge._window = type("Window", (), {"create_file_dialog": staticmethod(dialog)})()
    if case == "write_failure":
        monkeypatch.setattr(ConfigurationTransfer, "stage", lambda *args: (_ for _ in ()).throw(OSError("private path sentinel")))
    result = bridge.export_configuration()
    assert result.get("cancelled") is True if case == "cancel" else result["ok"] is False
    if dialogs:
        assert dialogs[0][0] == (webview.FileDialog.SAVE,)
        assert dialogs[0][1]["file_types"] == ("Configuration ZIP (*.zip)",)
    assert destination.read_bytes() == b"existing destination"
    assert "private path sentinel" not in json.dumps(result)
    assert webview.settings["ALLOW_DOWNLOADS"] is False


async def test_import_uses_normalized_model_values_from_existing_validator(profiles):
    transfer = profiles("profile")
    payload, _, _ = unpack_configuration(transfer.export()["archive_base64"])
    selected, fallback = payload["ai"]["selected_model"], payload["ai"]["fallback_model"]
    payload["ai"].update(selected_model=" " + selected + " ", fallback_model=" " + fallback + " ")
    encoded = pack_configuration(payload)
    transfer.apply(encoded, transfer.preview(encoded)["preview_token"], True)
    assert transfer.app.settings.gemini_model == selected
    assert transfer.app.settings.gemini_fallback_model == fallback
    assert transfer.settings.snapshot().ai.selected_model == selected
    assert transfer.settings.snapshot().ai.fallback_model == fallback


@pytest.mark.parametrize("old_format", [False, True])
async def test_desktop_import_preserves_destination_server_availability(profiles, old_format):
    source = profiles("desktop")
    seed(source)
    target = profiles("server")
    seed(target)  # Same names, independently created custom UUIDs.
    target.state.server_runtime = True
    target.state.apply_command_settings("ask", stream_availability="live_only")
    existing = target.custom.get_by_name("hello")
    target.custom.save({**existing.to_json(), "stream_availability": "offline_only"})
    encoded = source.export()["archive_base64"]
    payload, _, _ = unpack_configuration(encoded)
    assert "stream_availability" not in payload["commands"]["ask"]
    assert "stream_availability" not in payload["custom_commands"][0]
    if old_format:
        # Old format-1 archives also lack the optional new field.
        encoded = pack_configuration(payload)
    target.apply(encoded, target.preview(encoded)["preview_token"], True)
    assert target.state.get_command_settings("ask").stream_availability == "live_only"
    assert target.custom.get_by_name("greeting").stream_availability == "offline_only"
    replacement = build_application(target.app.settings)
    try:
        assert replacement.services.runtime_state.get_command_settings("ask").stream_availability == "live_only"
        assert replacement.custom_commands.get_by_name("hello").stream_availability == "offline_only"
        assert not replacement.services.runtime_state.server_runtime
        assert replacement.services.runtime_state.command_stream_available("live_only")
    finally:
        await replacement.shutdown()


async def test_server_export_transfers_explicit_anytime_and_restrictions(profiles):
    source = profiles("server-source")
    seed(source)
    source.state.server_runtime = True
    source.state.apply_command_settings("ask", stream_availability="live_only")
    target = profiles("server-target")
    seed(target)
    target.state.server_runtime = True
    existing = target.custom.get_by_name("hello")
    target.custom.save({**existing.to_json(), "stream_availability": "offline_only"})
    encoded = source.export()["archive_base64"]
    payload, _, _ = unpack_configuration(encoded)
    assert payload["commands"]["ask"]["stream_availability"] == "live_only"
    assert payload["custom_commands"][0]["stream_availability"] == "anytime"
    target.apply(encoded, target.preview(encoded)["preview_token"], True)
    assert target.state.get_command_settings("ask").stream_availability == "live_only"
    assert target.custom.get_by_name("hello").stream_availability == "anytime"
    # Server ZIPs also load on Desktop without enabling Server enforcement.
    target.state.server_runtime = False
    target.apply(encoded, target.preview(encoded)["preview_token"], True)
    assert target.state.command_stream_available("live_only")
