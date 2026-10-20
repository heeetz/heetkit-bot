"""Private headless credentials; external provisioning always remains authoritative."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from threading import RLock

from app.credentials import (
    CREDENTIAL_LABELS, MAX_CREDENTIAL_LENGTH, CredentialError, CredentialManager, CredentialName,
)


class ServerCredentialStore:
    """One bounded, atomic secret document in the private persistent profile.

    This is access-controlled storage, not encryption at rest. Never use ordinary
    configuration recovery/backups here: those have different disclosure rules.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def _check_path(self) -> None:
        if any(path.is_symlink() for path in (self.path, *self.path.parents)):
            raise CredentialError("Private credential storage must not use symbolic links.")

    def _read(self) -> dict[str, str]:
        try:
            self._check_path()
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or (os.name == "posix" and
                        (info.st_uid != os.geteuid() or info.st_mode & 0o077)):
                    raise ValueError
                raw = source.read(32769)
            if len(raw) > 32768:
                raise ValueError
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result
            data = json.loads(raw, object_pairs_hook=unique)
            if not isinstance(data, dict) or set(data) - {name.value for name in CredentialName}:
                raise ValueError
            for value in data.values():
                self.validate(value)
            return data
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, UnicodeError):
            raise CredentialError("Cannot read private server credentials. Restore a private backup or repair permissions while stopped.") from None

    @staticmethod
    def validate(value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[!-~]{1,8192}", value.strip()):
            raise CredentialError(f"Use a nonempty credential of at most {MAX_CREDENTIAL_LENGTH} visible ASCII characters.")
        return value.strip()

    def get(self, name: CredentialName) -> str | None:
        with self._lock:
            return self._read().get(name.value)

    def _write(self, data: dict[str, str]) -> None:
        temporary = None
        try:
            self._check_path()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name == "posix":
                os.chmod(self.path.parent, 0o700)
            descriptor, filename = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            temporary = Path(filename)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=True)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError:
            raise CredentialError("Could not save private server credentials. Check persistent storage permissions.") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def replace(self, name: CredentialName, value: str) -> None:
        value = self.validate(value)
        with self._lock:
            self._write(self._read() | {name.value: value})

    def remove(self, name: CredentialName) -> bool:
        with self._lock:
            data = self._read()
            if name.value not in data:
                return False
            del data[name.value]
            self._write(data)
            return True


class ServerCredentialManager(CredentialManager):
    def __init__(self, external, store: ServerCredentialStore) -> None:
        super().__init__(external, store=store)
        self.validation = {name: "not_tested" for name in CredentialName}

    def effective_value(self, name: CredentialName) -> str | None:
        # Unlike Desktop's fallback ordering, server external inputs cannot be
        # shadowed. Storage failures fail closed instead of hiding a broken file.
        return self._environment_fallbacks[name] or self._store.get(name)

    def statuses(self) -> tuple:
        # Server callers use the explicit projection below, never keyring status.
        return ()

    def server_statuses(self) -> list[dict]:
        return [{"name": name.value, "label": CREDENTIAL_LABELS[name],
            "configured": bool(self.effective_value(name)),
            "source": "environment" if self._environment_fallbacks[name] else
                      "server_file" if self._store.get(name) else "missing",
            "secure_storage_available": True, "managed": not bool(self._environment_fallbacks[name]),
            "validation_status": self.validation[name]} for name in (
                CredentialName.TWITCH_CLIENT_SECRET, CredentialName.GEMINI_API_KEY)]

    def check_managed(self, name: object) -> CredentialName:
        parsed = self.parse_name(name)
        if self._environment_fallbacks[parsed]:
            raise CredentialError("This credential is externally managed. Rotate or remove its environment/secret-file input and restart the server first.")
        return parsed

    def replace(self, name: object, value: object) -> None:
        parsed = self.check_managed(name)
        self._store.replace(parsed, self._store.validate(value))
        self.validation[parsed] = "not_tested"

    def remove(self, name: object) -> bool:
        parsed = self.check_managed(name)
        changed = self._store.remove(parsed)
        self.validation[parsed] = "not_tested"
        return changed
