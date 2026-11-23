"""One ``config.json`` for profile settings; migrates the 1.6 per-file layout once.

Each store owns one top-level section and its own validation. Writes re-read the
file under one process-wide lock per path and replace only their section, so
stores never overwrite each other's data. Secrets, tokens, people lists and filter
word lists stay in their own files.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from threading import Lock, RLock

from app.errors import UserError
from app.settings_recovery import _is_recovered, _unique_object

CONFIG_VERSION = 1
CONFIG_NAME = "config.json"
# Section name -> the 1.6 file it replaces.
LEGACY_FILES = {
    "app": "app_settings.json",
    "commands": "command_settings.json",
    "custom_commands": "custom_commands.json",
    "triggers": "message_triggers.json",
    "personalities": "personality_settings.json",
    "fun": "fun_settings.json",
    "announcements": "announcements.json",
}
BACKUP_NAME = "backup-1.6"

logger = logging.getLogger(__name__)
_locks: dict[Path, RLock] = {}
_locks_guard = Lock()


def _lock_for(path: Path) -> RLock:
    with _locks_guard:
        return _locks.setdefault(path.resolve(), RLock())


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
                                         delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def encode(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


class ConfigFile:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock = _lock_for(self.path)

    def section(self, name: str) -> ConfigSection:
        return ConfigSection(self, name)

    def read(self) -> dict:
        """Parsed document; raises FileNotFoundError, OSError or ValueError."""
        document = json.loads(self.path.read_bytes().decode("utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("config.json must contain an object")
        return document

    def load(self, name: str) -> object:
        """One section; a missing section raises FileNotFoundError like a missing file."""
        document = self.read()
        if name not in document:
            raise FileNotFoundError(name)
        return document[name]

    def save(self, sections: dict[str, object], *, recovered: dict[str, object | None],
             versions: dict[str, int] | None = None) -> None:
        """Replace sections atomically; refuse unreadable or future files.

        ``recovered`` holds what each store loaded. When the stored section holds
        anything else (unknown fields, skipped entries, outside edits), the whole
        file is first copied to a unique ``config.json.*.recovery`` file. ``None``
        always copies an existing section.
        """
        with self.lock:
            try:
                original = self.path.read_bytes()
            except FileNotFoundError:
                original = None
            except OSError as error:
                raise UserError("settings_recovery.cannot_save_profile", filename=self.path.name) from error
            document = self.checked(original, {name: (versions or {}).get(name) for name in sections})
            if any(name in document and not _is_recovered(document[name], recovered.get(name)) for name in sections):
                self.preserve(original)
            write_atomic(self.path, encode({**document, **sections}))

    def checked(self, original: bytes | None, versions: dict[str, int | None]) -> dict:
        """The stored document, refusing what a save must not overwrite.

        Unreadable or future files and sections with another ``version`` are refused.
        """
        if original is None:
            return {"schema_version": CONFIG_VERSION}
        repair = UserError("settings_recovery.cannot_save_profile", filename=self.path.name)
        try:
            document = json.loads(original.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        except (UnicodeError, ValueError) as error:
            raise repair from error
        if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
                or document["schema_version"] != CONFIG_VERSION):
            raise repair
        for name, version in versions.items():
            current = document.get(name)
            if version is not None and name in document and (
                    not isinstance(current, dict) or type(current.get("version")) is not int
                    or current["version"] != version):
                raise repair
        return document

    def preserve(self, original: bytes) -> None:
        recovery: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=f"{self.path.name}.",
                                             suffix=".recovery", delete=False) as output:
                recovery = Path(output.name)
                output.write(original)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            if recovery is not None:
                recovery.unlink(missing_ok=True)
            raise
        logger.warning("Preserved unrecovered settings before save path=%s recovery=%s", self.path, recovery)


class ConfigSection:
    """The part of ``config.json`` one store owns."""

    def __init__(self, file: ConfigFile, name: str) -> None:
        self.file, self.name = file, name

    @property
    def path(self) -> Path:
        return self.file.path

    def load(self) -> object:
        return self.file.load(self.name)

    def save(self, payload: object, *, recovered: object | None, version: int | None = None) -> None:
        self.file.save({self.name: payload}, recovered={self.name: recovered},
                       versions=None if version is None else {self.name: version})


def migrate_config(config_dir: Path, default_triggers: Path) -> None:
    """Create ``config.json`` once: from the 1.6 files (backed up first) or defaults.

    An unreadable 1.6 file is left out of ``config.json``; its exact bytes stay in
    the backup. The old files are removed only after ``config.json`` is durable.
    """
    target = config_dir / CONFIG_NAME
    if target.exists():
        return
    found = {name: config_dir / filename for name, filename in LEGACY_FILES.items()
             if (config_dir / filename).is_file()}
    document: dict[str, object] = {"schema_version": CONFIG_VERSION}
    if found:
        backup = config_dir / BACKUP_NAME
        suffix = 1
        while backup.exists():
            suffix += 1
            backup = config_dir / f"{BACKUP_NAME}-{suffix}"
        backup.mkdir()
        for name, path in found.items():
            shutil.copy2(path, backup / path.name)
            try:
                document[name] = json.loads(path.read_bytes().decode("utf-8-sig"))
            except (UnicodeError, ValueError):
                logger.warning("Could not migrate unreadable settings file=%s; original kept in %s",
                               path.name, backup.name)
    if "triggers" not in found:
        document["triggers"] = json.loads(default_triggers.read_text(encoding="utf-8"))
    write_atomic(target, encode(document))
    for path in found.values():
        path.unlink()
    if found:
        logger.info("Moved %d settings files into %s; originals in %s", len(found), CONFIG_NAME, backup.name)
