"""OS-backed storage and validation for user-entered credentials."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

import httpx
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

logger = logging.getLogger(__name__)

CREDENTIAL_SERVICE_NAME = "twitch-bot"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
MAX_CREDENTIAL_LENGTH = 8_192


class CredentialName(StrEnum):
    GEMINI_API_KEY = "gemini_api_key"
    TWITCH_CLIENT_SECRET = "twitch_client_secret"


CREDENTIAL_LABELS = {
    CredentialName.GEMINI_API_KEY: "Gemini API key",
    CredentialName.TWITCH_CLIENT_SECRET: "Twitch client secret",
}


class CredentialError(RuntimeError):
    """Safe credential error suitable for the desktop bridge."""


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    name: str
    label: str
    configured: bool
    source: str
    secure_storage_available: bool

    def serialize(self) -> dict[str, object]:
        return asdict(self)


class CredentialStore:
    """Small wrapper around the operating system credential backend."""

    def __init__(self, backend: KeyringBackend = keyring) -> None:
        self._backend = backend

    def get(self, name: CredentialName) -> str | None:
        try:
            value = self._backend.get_password(CREDENTIAL_SERVICE_NAME, name.value)
        except KeyringError as error:
            raise CredentialError("Secure credential storage is unavailable.") from error
        return value or None

    def replace(self, name: CredentialName, value: str) -> None:
        try:
            self._backend.set_password(CREDENTIAL_SERVICE_NAME, name.value, value)
        except KeyringError as error:
            raise CredentialError("Could not store the credential securely.") from error

    def remove(self, name: CredentialName) -> bool:
        if self.get(name) is None:
            return False
        try:
            self._backend.delete_password(CREDENTIAL_SERVICE_NAME, name.value)
        except PasswordDeleteError:
            return False
        except KeyringError as error:
            raise CredentialError("Could not remove the stored credential.") from error
        return True


class CredentialManager:
    """Overlay secure credentials over private environment fallbacks."""

    def __init__(
        self,
        environment_fallbacks: Mapping[CredentialName, str | None],
        store: CredentialStore | None = None,
    ) -> None:
        self._environment_fallbacks = {
            name: environment_fallbacks.get(name) for name in CredentialName
        }
        self._store = store or CredentialStore()

    @staticmethod
    def parse_name(name: object) -> CredentialName:
        if not isinstance(name, str):
            raise ValueError("Unknown credential.")
        try:
            return CredentialName(name)
        except ValueError as error:
            raise ValueError("Unknown credential.") from error

    def _secure_value(self, name: CredentialName) -> tuple[str | None, bool]:
        try:
            return self._store.get(name), True
        except CredentialError as error:
            logger.warning(
                "Secure credential storage read failed name=%s error_type=%s",
                name.value,
                type(error.__cause__).__name__ if error.__cause__ else type(error).__name__,
            )
            return None, False

    def effective_value(self, name: CredentialName) -> str | None:
        secure_value, _ = self._secure_value(name)
        return secure_value or self._environment_fallbacks[name]

    def settings_overrides(self) -> dict[str, str | None]:
        return {
            name.value: self.effective_value(name)
            for name in CredentialName
        }

    def statuses(self) -> tuple[CredentialStatus, ...]:
        statuses = []
        for name in CredentialName:
            secure_value, secure_storage_available = self._secure_value(name)
            fallback_value = self._environment_fallbacks[name]
            source = (
                "credential_store"
                if secure_value is not None
                else "environment"
                if fallback_value is not None
                else "missing"
            )
            statuses.append(
                CredentialStatus(
                    name=name.value,
                    label=CREDENTIAL_LABELS[name],
                    configured=secure_value is not None or fallback_value is not None,
                    source=source,
                    secure_storage_available=secure_storage_available,
                )
            )
        return tuple(statuses)

    def replace(self, name: object, value: object) -> None:
        parsed_name = self.parse_name(name)
        if not isinstance(value, str):
            raise ValueError("Credential must be text.")
        normalized = value.strip()
        if not normalized:
            raise ValueError("Credential must not be empty.")
        if len(normalized) > MAX_CREDENTIAL_LENGTH:
            raise ValueError(
                f"Credential must not exceed {MAX_CREDENTIAL_LENGTH} characters."
            )
        self._store.replace(parsed_name, normalized)

    def remove(self, name: object) -> bool:
        return self._store.remove(self.parse_name(name))

    async def test(
        self,
        name: object,
        *,
        http_client: httpx.AsyncClient,
        twitch_client_id: str,
    ) -> None:
        parsed_name = self.parse_name(name)
        value = self.effective_value(parsed_name)
        if value is None:
            raise CredentialError("Credential is not configured.")

        try:
            if parsed_name is CredentialName.GEMINI_API_KEY:
                response = await http_client.get(
                    GEMINI_MODELS_URL,
                    headers={"x-goog-api-key": value},
                    params={"pageSize": 1},
                )
            else:
                response = await http_client.post(
                    TWITCH_TOKEN_URL,
                    data={
                        "client_id": twitch_client_id,
                        "client_secret": value,
                        "grant_type": "client_credentials",
                    },
                )
        except httpx.RequestError as error:
            raise CredentialError("Credential service could not be reached.") from error

        if 200 <= response.status_code < 300:
            return
        if response.status_code in {400, 401, 403}:
            raise CredentialError("Credential was rejected by the provider.")
        raise CredentialError("Credential could not be verified by the provider.")
