"""Bounded portable configuration, coordinated with the existing profile stores.

Only generated, validated configuration is written. ZIP member names never become
filesystem paths. All calls run synchronously on the owning core loop, under the
stores' existing locks, so bot events cannot observe a partial publication.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import secrets
import stat
import tempfile
import time
import zipfile
import zlib
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

from app.ai_user_blocks import BlockedAIUser, normalize_ai_username, verified_user_id
from app.app_settings import APP_SETTINGS_VERSION
from app.announcements import parse_announcements
from app.command_settings import CommandSettings, CommandSettingsOverride
from app.config.ai_language import validate_response_language
from app.config.ai_models import validate_ai_provider, validate_provider_models
from app.config.ai_setup import parse_ai_setup
from app.config.personalities import AI_PERSONALITY_PROMPTS
from app.custom_commands import parse_custom_command
from app.filter_settings import apply_filter_settings, validate_filter_input
from app.fun_settings import _validate_responses
from app.message_triggers import _TRIGGER_FIELDS, parse_message_trigger
from app.personality_settings import (
    validate_personality_name, validate_personality_prompt, validate_profile_instructions,
)
from app.runtime_paths import FILTER_NAMES
from app.runtime_state import RuntimeState
from app.settings_recovery import preserve_settings_recovery
from app.version import VERSION


FORMAT_VERSION = 1
MAX_ARCHIVE = 1024 * 1024
MAX_CONFIGURATION = 768 * 1024
MAX_LOCAL_FILE = 8 * 1024 * 1024
MAX_TRANSFER_BODY = 4 * ((MAX_ARCHIVE + 2) // 3) + 1024
SECTIONS = ("commands", "responses", "custom_commands", "personalities", "ai", "filters", "blocked_users", "triggers", "announcements")
EFFECTS = ["All included settings are saved and apply to subsequent bot processing immediately.",
           "In-flight replies may finish with earlier settings. No reconnect or restart is required."]
PRESERVED = ["Twitch identity, channel and authorization", "Provider and management credentials",
             "SQLite history and privacy policy", "Operation mode, desktop startup/window settings and machine paths"]


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration key.")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("Non-finite configuration value.")


def _json(raw):
    value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)

    def check(item, depth=0):
        if depth > 16:
            raise ValueError("Configuration nesting exceeds its limit.")
        if isinstance(item, str):
            item.encode("utf-8")  # Reject escaped lone surrogates as invalid text.
        elif isinstance(item, dict):
            for key, entry in item.items():
                check(key, depth + 1)
                check(entry, depth + 1)
        elif isinstance(item, list):
            for entry in item:
                check(entry, depth + 1)

    check(value)
    return value


def _encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True).encode("utf-8")


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unexpected or missing configuration fields.")


def _list(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Configuration collection exceeds its limit.")
    return value


def pack_configuration(configuration):
    raw = _encode(configuration)
    if len(raw) > MAX_CONFIGURATION:
        raise ValueError("Configuration exceeds the portable transfer limit (768 KiB).")
    manifest = {"format": "heetkit-configuration", "format_version": FORMAT_VERSION,
                "application_version": VERSION,
                "files": {"configuration.json": {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}}
    output = io.BytesIO()
    # Stored output avoids rejecting our own highly repetitive prompts as bombs.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", _encode(manifest))
        archive.writestr("configuration.json", raw)
    return base64.b64encode(output.getvalue()).decode("ascii")


def unpack_configuration(encoded):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_ARCHIVE + 2) // 3):
        raise ValueError("Select a configuration ZIP of at most 1 MiB.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_ARCHIVE:
            raise ValueError
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 2 or {item.filename for item in members} != {"manifest.json", "configuration.json"}:
                raise ValueError
            if archive.comment:
                raise ValueError
            contents = {}
            for item in members:
                kind = stat.S_IFMT(item.external_attr >> 16)
                limit = 4096 if item.filename == "manifest.json" else MAX_CONFIGURATION
                if (item.orig_filename != item.filename or kind not in (0, stat.S_IFREG)
                        or item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or item.extra or not 0 < item.file_size <= limit
                        or item.file_size > max(1, item.compress_size) * 100):
                    raise ValueError
                with archive.open(item) as source:
                    data = source.read(limit + 1)
                if len(data) != item.file_size:
                    raise ValueError
                contents[item.filename] = data
        manifest = _json(contents["manifest.json"])
        _fields(manifest, ("format", "format_version", "application_version", "files"))
        if (manifest["format"] != "heetkit-configuration" or type(manifest["format_version"]) is not int
                or manifest["format_version"] != FORMAT_VERSION
                or not isinstance(manifest["application_version"], str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)", manifest["application_version"])):
            raise ValueError
        _fields(manifest["files"], ("configuration.json",))
        record = manifest["files"]["configuration.json"]
        _fields(record, ("size", "sha256"))
        data = contents["configuration.json"]
        if (type(record["size"]) is not int or record["size"] != len(data)
                or record["sha256"] != hashlib.sha256(data).hexdigest()):
            raise ValueError
        return _json(data), manifest, hashlib.sha256(raw).hexdigest()
    except (ValueError, TypeError, UnicodeError, RecursionError, binascii.Error, zipfile.BadZipFile,
            NotImplementedError, RuntimeError, EOFError, OSError, zlib.error) as error:
        raise ValueError("Invalid, unsupported or unsafe configuration ZIP.") from error


class ConfigurationTransfer:
    def __init__(self, application, app_settings):
        self.app = application
        self.settings = app_settings
        self.state = application.services.runtime_state
        self.custom = application.custom_commands
        self.fun = application.fun_settings
        self.blocks = application.services.ai_user_blocks
        self.triggers = application.dispatcher._message_triggers
        self.announcements = application.announcements
        self.config = app_settings._path.parent
        self.pending = {}

    @contextmanager
    def locked(self):
        with ExitStack() as stack:
            for lock in (self.state.command_namespace_lock, self.settings._lock, self.fun._lock,
                         self.blocks._lock, self.triggers._lock, self.announcements._lock):
                stack.enter_context(lock)
            yield

    def snapshot(self):
        state = self.state
        words, phrases, patterns = self.app.services.filter_manager.snapshot()
        return {
            "commands": {name: {**asdict(value), "permission": value.permission.name,
                                   "aliases": list(value.aliases)}
                         for name in state.runtime_toggleable_commands
                         for value in (state.get_command_settings(name),)},
            "responses": {name: self.fun.snapshot(name)["responses"] for name in ("fate", "tg")},
            "custom_commands": [item.to_json() for item in self.custom.list()],
            "personalities": asdict(state.get_personality_settings_snapshot()[0]),
            "ai": {"memory_enabled": state.ai_memory_enabled,
                   "provider": self.app.settings.ai_provider,
                   "selected_model": self.app.settings.gemini_model,
                   "fallback_model": self.app.settings.gemini_fallback_model,
                   "deepseek_selected_model": self.app.settings.deepseek_model,
                   "deepseek_fallback_model": self.app.settings.deepseek_fallback_model,
                   "openai_selected_model": self.app.settings.openai_model,
                   "openai_fallback_model": self.app.settings.openai_fallback_model,
                   "setup": asdict(self.app.settings.ai_setup) if self.app.settings.ai_setup is not None else None,
                   "response_language": asdict(self.app.settings.ai_response_language)},
            "filters": {"words": list(words), "phrases": list(phrases), "patterns": [item.pattern for item in patterns]},
            "blocked_users": [asdict(item) for item in self.blocks.list()],
            "triggers": [asdict(item) for item in self.triggers.list()],
            "announcements": [item.to_json() for item in self.announcements.list()],
        }

    def validate(self, payload):
        from app.management import ApplicationManagement

        # Older format-1 archives know nothing about schedules. Preserve the
        # destination collection; explicit [] in a new archive clears it.
        _fields(payload, SECTIONS if isinstance(payload, dict) and "announcements" in payload else SECTIONS[:-1])
        _fields(payload["commands"], self.state.runtime_toggleable_commands)
        commands = {}
        for name, value in payload["commands"].items():
            fields = set(CommandSettings.__dataclass_fields__) - {"stream_availability", "primary_name"}
            if isinstance(value, dict) and "primary_name" in value:
                fields.add("primary_name")
            if isinstance(value, dict) and "stream_availability" in value:
                fields.add("stream_availability")
            _fields(value, fields)
            _fields(value["cooldown"], ("per_user_seconds", "global_seconds"))
            cooldown = value["cooldown"]
            # Same finite/nonnegative and administrative bounds as management edits.
            _, policy, permission = ApplicationManagement._parse_command_settings(
                value["enabled"], cooldown["per_user_seconds"], cooldown["global_seconds"], value["permission"])
            commands[name] = CommandSettings(**{"primary_name": name,
                                                 "stream_availability": self.state.get_command_settings(name).stream_availability,
                                                 **value, "cooldown": policy, "permission": permission,
                                                 "aliases": tuple(_list(value["aliases"], 10))})
        customs = {}
        for raw in _list(payload["custom_commands"], 1000):
            if not isinstance(raw, dict) or set(raw) - {"id", "name", "enabled", "responses", "permission",
                    "per_user_seconds", "global_seconds", "aliases", "response_mode", "burst_count",
                    "burst_allow_override", "burst_interval_ms", "stream_availability"}:
                raise ValueError("Unknown custom command fields.")
            if "stream_availability" not in raw:
                # Desktop/older exports carry no Server policy. Preserve the
                # matching destination command, also when its local UUID differs.
                existing = next((item for item in self.custom.list() if item.id == raw.get("id")), None)
                if existing is None and isinstance(raw.get("name"), str):
                    existing = next((item for item in self.custom.list() if item.name == raw["name"]), None)
                if existing is not None:
                    raw = {**raw, "stream_availability": existing.stream_availability}
            command = parse_custom_command(raw)
            if command.id in customs:
                raise ValueError("Duplicate custom command.")
            customs[command.id] = command
        # Validate the complete replacement namespace, rather than conflicting
        # with destination commands that this import will itself replace.
        candidate = RuntimeState()
        candidate.configure_commands(self.app.registry.definitions())
        candidate._command_settings = commands
        candidate._custom_commands = SimpleNamespace(list=lambda: tuple(customs.values()))
        for name, value in commands.items():
            if candidate._validated_command_settings(name, value) != value:
                raise ValueError("Removed commands must be disabled.")
        used = candidate.reserved_command_names()
        for command in customs.values():
            for name in (command.name, *command.aliases):
                if name in used:
                    raise ValueError("Duplicate command name or alias.")
                used.add(name)
        _fields(payload["responses"], ("fate", "tg"))
        responses = {name: _validate_responses(payload["responses"][name], max_responses=limit)
                     for name, limit in (("fate", 1000), ("tg", 1))}
        personality = payload["personalities"]
        _fields(personality, ("active_personality", "overrides", "profile_instructions"))
        prompts = personality["overrides"]
        if (not isinstance(prompts, dict) or not 1 <= len(prompts) <= 200
                or not AI_PERSONALITY_PROMPTS.keys() <= prompts.keys()):
            raise ValueError("Invalid personality collection.")
        names = set()
        for name, prompt in prompts.items():
            if validate_personality_name(name) != name or name.casefold() in names:
                raise ValueError("Invalid or duplicate personality name.")
            names.add(name.casefold())
            validate_personality_prompt(prompt)
        if not isinstance(personality["active_personality"], str) or personality["active_personality"] not in prompts:
            raise ValueError("Unknown active personality.")
        validate_profile_instructions(personality["profile_instructions"])
        ai = payload["ai"]
        legacy_ai_fields = {"memory_enabled", "selected_model", "fallback_model", "response_language"}
        provider_fields = {"provider", "deepseek_selected_model", "deepseek_fallback_model"}
        if set(ai) - {"setup"} == legacy_ai_fields:
            # Format-1 Gemini archives must never reinterpret their model choices.
            ai = {**ai, "provider": "gemini", "deepseek_selected_model": self.app.settings.deepseek_model,
                  "deepseek_fallback_model": self.app.settings.deepseek_fallback_model}
        openai_fields = {"openai_selected_model", "openai_fallback_model"}
        if not (set(ai) & openai_fields):
            ai = {**ai, "openai_selected_model": self.app.settings.openai_model,
                  "openai_fallback_model": self.app.settings.openai_fallback_model}
        ai = {"setup": None, **ai}
        _fields(ai, legacy_ai_fields | provider_fields | openai_fields | {"setup"})
        setup = parse_ai_setup(ai["setup"], require_consent=False) if ai["setup"] is not None else None
        if setup and setup.fallback and setup.fallback.provider != setup.primary.provider:
            # Portable consent never grants a new destination permission to route.
            setup = replace(setup, cross_provider_acknowledged=False)
        if type(ai["memory_enabled"]) is not bool:
            raise ValueError("Invalid AI memory setting.")
        selected_model, fallback_model = validate_provider_models("gemini", ai["selected_model"], ai["fallback_model"])
        deepseek_selected, deepseek_fallback = validate_provider_models("deepseek", ai["deepseek_selected_model"], ai["deepseek_fallback_model"])
        openai_selected, openai_fallback = validate_provider_models("openai", ai["openai_selected_model"], ai["openai_fallback_model"])
        ai = {**ai, "provider": validate_ai_provider(ai["provider"]), "selected_model": selected_model,
              "fallback_model": fallback_model, "deepseek_selected_model": deepseek_selected,
              "deepseek_fallback_model": deepseek_fallback, "openai_selected_model": openai_selected,
              "openai_fallback_model": openai_fallback}
        if setup and setup.primary.provider != ai["provider"]:
            raise ValueError("AI provider and primary selection disagree.")
        _fields(ai["response_language"], ("mode", "allowed_languages", "fallback_language"))
        language = validate_response_language(**ai["response_language"])
        filters = validate_filter_input(payload["filters"])
        users, names, ids = [], set(), set()
        for raw in _list(payload["blocked_users"], 5000):
            _fields(raw, ("username", "twitch_user_id"))
            name = normalize_ai_username(raw["username"])
            identifier = raw["twitch_user_id"]
            if name in names or (identifier is not None and (verified_user_id(identifier) is None or identifier in ids)):
                raise ValueError("Invalid or duplicate AI user block.")
            users.append(BlockedAIUser(name, identifier))
            names.add(name)
            ids.add(identifier)
        triggers, used = [], set()
        for raw in _list(payload["triggers"], 100):
            _fields(raw, _TRIGGER_FIELDS)
            trigger = parse_message_trigger(raw)
            if trigger.id in used:
                raise ValueError("Duplicate trigger ID.")
            triggers.append(trigger)
            used.add(trigger.id)
        return SimpleNamespace(commands=commands, customs=customs, responses=responses,
                               personality=personality, ai=ai, setup=setup, language=language, filters=filters,
                               users=tuple(users), triggers=tuple(triggers),
                               announcements=parse_announcements(payload["announcements"])
                                   if "announcements" in payload else self.announcements.list())

    def paths(self):
        return [self.state._command_settings_path, self.custom._path, self.state._personality_settings_path,
                self.fun.path, self.settings._path, self.blocks._path, self.triggers._path, self.announcements._path,
                *(self.config / "filters" / name for name in FILTER_NAMES)]

    def originals(self):
        originals = {}
        for path in self.paths():
            if path is None or not path.is_relative_to(self.config):
                raise ValueError("Configuration stores do not share this profile.")
            # Refuse local links/reparse points too; backup and replacement must
            # remain inside the profile even when its contents were edited manually.
            for part in (path, *path.parents):
                if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                    raise ValueError("Linked configuration paths are not supported.")
            try:
                with path.open("rb") as source:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise ValueError("Configuration must use regular files.")
                    data = source.read(MAX_LOCAL_FILE + 1)
                if len(data) > MAX_LOCAL_FILE:
                    raise ValueError("Existing configuration exceeds the backup limit.")
            except FileNotFoundError:
                data = None
            originals[path] = data
        return originals

    def fingerprint(self, originals):
        digest = hashlib.sha256(_encode(self.snapshot()))
        for path, data in originals.items():
            digest.update(str(path.relative_to(self.config)).encode())
            digest.update(b"missing" if data is None else hashlib.sha256(data).digest())
        return digest.hexdigest()

    def export(self):
        with self.locked():
            payload = self.snapshot()
            if self.state.server_runtime:
                for raw, item in zip(payload["custom_commands"], self.custom.list()):
                    raw["stream_availability"] = item.stream_availability
            else:
                for raw in (*payload["commands"].values(), *payload["custom_commands"]):
                    raw.pop("stream_availability", None)
            # Normalize tuples through JSON before using the strict wire validators.
            self.validate(_json(_encode(payload)))
            return {"ok": True, "filename": f"HeetKit-configuration-{VERSION}.zip",
                    "archive_base64": pack_configuration(payload)}

    def preview(self, encoded):
        payload, manifest, digest = unpack_configuration(encoded)
        with self.locked():
            self.validate(payload)
            fingerprint = self.fingerprint(self.originals())
            current = self.snapshot()
            now = time.monotonic()
            self.pending = {key: value for key, value in self.pending.items() if value[0] > now}
            if len(self.pending) >= 8:
                del self.pending[next(iter(self.pending))]
            token = secrets.token_urlsafe(32)
            self.pending[token] = (now + 600, digest, fingerprint)
        return {"ok": True, "preview_token": token, "format_version": FORMAT_VERSION,
                "application_version": manifest["application_version"],
                "sections": [{"name": name, "incoming_count": self.count(name, payload[name]),
                              "current_count": self.count(name, current[name]), "details": self.details(name, payload[name])}
                             for name in SECTIONS if name in payload], "effects": EFFECTS, "preserved": PRESERVED}

    @staticmethod
    def count(name, value):
        if name == "personalities":
            return len(value["overrides"])
        if name in ("responses", "filters"):
            return sum(map(len, value.values()))
        return len(value)

    @staticmethod
    def details(name, value):
        if name == "commands":
            return ["!" + key for key in value]
        if name == "custom_commands":
            return ["!" + item["name"] for item in value]
        if name == "announcements":
            return [item["name"] for item in value]
        if name == "personalities":
            return ["Selected: " + value["active_personality"], *value["overrides"], "Profile instructions included"]
        if name == "ai":
            setup = value.get("setup")
            if setup:
                def selection_label(selection):
                    return (f"{selection['provider']} / {selection['model']}; thinking {selection['thinking']}; "
                            f"search {'on' if selection['search'] else 'off'}")
                routing = ["Imported cross-provider fallback is unavailable until acknowledged and saved in AI setup."] if setup.get("fallback") and setup["fallback"]["provider"] != setup["primary"]["provider"] else []
                return routing + ["Memory: " + ("enabled" if value["memory_enabled"] else "disabled"),
                    "Primary: " + selection_label(setup["primary"]),
                    "Fallback: " + (selection_label(setup["fallback"]) if setup.get("fallback") else "disabled"),
                    f"Question/answer limits: {setup.get('max_question_length', 300)}/{setup.get('max_answer_length', 220)} characters",
                    "Shared instructions: " + ("shipped defaults" if setup.get("shared_instructions") is None else "custom (included)"),
                    "Response language: " + value["response_language"]["mode"]]
            prefix = value["provider"] + "_" if value.get("provider", "gemini") != "gemini" else ""
            return ["Memory: " + ("enabled" if value["memory_enabled"] else "disabled"),
                    "Provider: " + value.get("provider", "gemini"),
                    "Model: " + value[prefix + "selected_model"], "Fallback: " + value[prefix + "fallback_model"],
                    "Response language: " + value["response_language"]["mode"]]
        if name in ("filters", "responses"):
            return [f"{key}: {len(entries)}" for key, entries in value.items()]
        return [item["username" if name == "blocked_users" else "id"] for item in value]

    def apply(self, encoded, token, confirmed):
        if confirmed is not True or not isinstance(token, str):
            raise ValueError("Preview and explicitly confirm the configuration import first.")
        payload, _, digest = unpack_configuration(encoded)
        with self.locked():
            plan = self.pending.pop(token, None)
            originals = self.originals()
            if (plan is None or plan[0] <= time.monotonic() or plan[1] != digest
                    or plan[2] != self.fingerprint(originals)):
                raise ValueError("Preview expired or configuration changed. Preview the ZIP again.")
            parsed = self.validate(payload)
            self.commit(parsed, originals)
            self.app.announcement_scheduler.reset()
        return {"ok": True, "effects": EFFECTS}

    def commit(self, parsed, originals):
        state = self.state
        overrides = {name: CommandSettingsOverride.from_settings(value, state.get_command_default_settings(name))
                     for name, value in parsed.commands.items()}
        overrides = {name: value for name, value in overrides.items() if not value.is_empty}
        old_app = self.settings.snapshot()
        new_ai = replace(old_app.ai, memory_enabled=parsed.ai["memory_enabled"],
                         selected_model=parsed.ai["selected_model"], fallback_model=parsed.ai["fallback_model"],
                         provider=parsed.ai["provider"], deepseek_selected_model=parsed.ai["deepseek_selected_model"],
                         deepseek_fallback_model=parsed.ai["deepseek_fallback_model"],
                         openai_selected_model=parsed.ai["openai_selected_model"],
                         openai_fallback_model=parsed.ai["openai_fallback_model"],
                         response_language=parsed.language, setup=parsed.setup)
        app_payload = {"version": APP_SETTINGS_VERSION, **asdict(old_app)}
        if originals[self.settings._path] is not None:
            existing = _json(originals[self.settings._path])
            if "version" in existing:
                app_payload = existing
        app_payload = {**app_payload, "ai": {**app_payload.get("ai", {}), **asdict(new_ai)}}
        old_fun = (self.fun._payload if originals[self.fun.path] is None else _json(originals[self.fun.path]))
        fun_payload = {**old_fun, "fates": list(parsed.responses["fate"]),
                       "tg_message": parsed.responses["tg"][0]}
        values = [
            {name: value.to_json() for name, value in overrides.items() if not value.is_empty},
            {"version": 2, "commands": [item.to_json() for item in parsed.customs.values()]},
            parsed.personality, fun_payload, app_payload,
            self.blocks._payload(parsed.users),
            {"version": 1, "triggers": [asdict(item) for item in parsed.triggers]},
            {"version": 1, "announcements": [item.to_json() for item in parsed.announcements]},
        ]
        # Existing recovery rules refuse corrupt/future local stores. Exact import
        # backups additionally preserve every affected file, even fully valid ones.
        for index, path in enumerate(self.paths()[:8]):
            preserve_settings_recovery(path, None, version={1: (1, 2), 3: 1, 4: 1, 5: 1, 6: 1, 7: 1}.get(index),
                                       allow_legacy=index == 4, encoding="utf-8-sig" if index == 6 else "utf-8")
        files = dict(zip(self.paths()[:8], map(_encode, values)))
        for path, rules in zip(self.paths()[8:], (parsed.filters[0], parsed.filters[1], [rule.pattern for rule in parsed.filters[2]])):
            files[path] = "".join(f"{rule}\n" for rule in rules).encode("utf-8")
        backup_root = self.config / "import-backups"
        if backup_root.is_symlink() or (hasattr(backup_root, "is_junction") and backup_root.is_junction()):
            raise ValueError("Linked backup directories are not supported.")
        backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup = Path(tempfile.mkdtemp(prefix="configuration-", dir=backup_root))
        for index, (path, data) in enumerate(originals.items()):
            if data is not None:
                self.write_new(backup / f"{index}.original", data)
        self.write_new(backup / "manifest.json", _encode({"files": [
            {"path": path.relative_to(self.config).as_posix(), "backup": f"{index}.original" if data is not None else None}
            for index, (path, data) in enumerate(originals.items())]}))
        staged, replaced = {}, []
        # Publication is last. Capture just owned configuration attributes so an
        # unexpected publication failure can also restore active unsaved settings.
        owners = (state, self.custom, self.fun, self.settings, self.blocks, self.triggers, self.announcements,
                  self.app.services.filter_manager)
        snapshots = [(owner, dict(vars(owner))) for owner in owners]
        old_effective = (self.app.settings.gemini_model, self.app.settings.gemini_fallback_model,
                         self.app.settings.ai_response_language, self.app.settings.ai_provider,
                         self.app.settings.deepseek_model, self.app.settings.deepseek_fallback_model,
                         self.app.settings.openai_model, self.app.settings.openai_fallback_model,
                         self.app.settings.ai_setup)
        try:
            for path, data in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                staged[path] = self.stage(path, data)
            for path, temporary in staged.items():
                os.replace(temporary, path)
                replaced.append(path)
            self.publish(parsed, overrides, replace(old_app, ai=new_ai), fun_payload)
        except BaseException:
            rollback_failed = False
            for path in reversed(replaced):
                try:
                    if originals[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        temporary = self.stage(path, originals[path])
                        try:
                            os.replace(temporary, path)
                        finally:
                            temporary.unlink(missing_ok=True)
                except OSError:
                    rollback_failed = True
            for owner, snapshot in snapshots:
                vars(owner).clear()
                vars(owner).update(snapshot)
            (self.app.settings.gemini_model, self.app.settings.gemini_fallback_model,
             self.app.settings.ai_response_language, self.app.settings.ai_provider,
             self.app.settings.deepseek_model, self.app.settings.deepseek_fallback_model,
             self.app.settings.openai_model, self.app.settings.openai_fallback_model,
             self.app.settings.ai_setup) = old_effective
            if rollback_failed:
                raise OSError("Import rollback needs recovery from config/import-backups; stop the application and restore affected files.") from None
            raise
        finally:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def write_new(path, data):
        with path.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())

    @staticmethod
    def stage(path, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".configuration-", delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            return temporary
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    def publish(self, parsed, overrides, app_settings, fun_payload):
        state = self.state
        state._command_settings = parsed.commands
        state._persisted_command_overrides = overrides
        state._personality_prompts = dict(parsed.personality["overrides"])
        state._persisted_personality_overrides = dict(parsed.personality["overrides"])
        state._active_ai_personality = state._persisted_active_ai_personality = parsed.personality["active_personality"]
        state._profile_instructions = state._persisted_profile_instructions = parsed.personality["profile_instructions"]
        state.set_ai_memory_enabled(parsed.ai["memory_enabled"])
        self.custom._publish(parsed.customs)
        self.custom._schema_version = 2
        self.fun._payload = fun_payload
        for name, responses in parsed.responses.items():
            self.fun._set_responses(name, responses, saved=True)
        self.settings._settings = app_settings
        self.blocks._users = parsed.users
        self.triggers._triggers = parsed.triggers
        self.announcements._announcements = parsed.announcements
        self.app.settings.gemini_model = parsed.ai["selected_model"]
        self.app.settings.gemini_fallback_model = parsed.ai["fallback_model"]
        self.app.settings.ai_provider = parsed.ai["provider"]
        self.app.settings.deepseek_model = parsed.ai["deepseek_selected_model"]
        self.app.settings.deepseek_fallback_model = parsed.ai["deepseek_fallback_model"]
        self.app.settings.openai_model = parsed.ai["openai_selected_model"]
        self.app.settings.openai_fallback_model = parsed.ai["openai_fallback_model"]
        self.app.settings.ai_response_language = parsed.language
        self.app.settings.ai_setup = parsed.setup
        apply_filter_settings(self.app.services.filter_manager, parsed.filters)
