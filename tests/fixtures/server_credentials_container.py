"""Offline UID/volume persistence check; run twice in disposable Linux containers."""

import os
from pathlib import Path
import stat
import sys

from app.config.settings import Settings
from app.credentials import CredentialError, CredentialName
from app.server_setup import credential_manager


assert os.geteuid() == 10001
assert not any(os.environ.get(name) for name in (
    "TWITCH_CLIENT_SECRET", "GEMINI_API_KEY", "TWITCH_CLIENT_SECRET_FILE", "GEMINI_API_KEY_FILE"))
assert os.environ["HEETKIT_DATA_DIR"] == "/var/lib/heetkit"
manager = credential_manager(Settings())
path = Path("/var/lib/heetkit/auth/server_credentials.json")
if sys.argv[1] == "create":
    assert not path.exists()
    manager.replace("gemini_api_key", "synthetic-gemini")
    manager.replace("twitch_client_secret", "synthetic-twitch")
else:
    assert manager.effective_value(CredentialName.GEMINI_API_KEY) == "synthetic-gemini"
    assert manager.effective_value(CredentialName.TWITCH_CLIENT_SECRET) == "synthetic-twitch"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    path.chmod(0o644)
    try:
        manager.effective_value(CredentialName.GEMINI_API_KEY)
    except CredentialError:
        pass
    else:
        raise AssertionError("Permissive credential file was accepted")
    path.chmod(0o600)
    original = path.read_bytes()
    path.unlink()
    other = path.parent / "unrelated"
    other.write_bytes(original)
    path.symlink_to(other)
    try:
        manager.replace("gemini_api_key", "must-not-write")
    except CredentialError:
        pass
    else:
        raise AssertionError("Credential symlink was accepted")
    assert other.read_bytes() == original
    path.unlink()
    path.write_bytes(original)
    path.chmod(0o600)
    assert manager.remove("gemini_api_key")
    assert not manager.effective_value(CredentialName.GEMINI_API_KEY)
    assert manager.effective_value(CredentialName.TWITCH_CLIENT_SECRET) == "synthetic-twitch"
assert "keyring" not in sys.modules
print("Synthetic Linux credential check passed: " + sys.argv[1])
