"""OS-backed storage and validation for user-entered credentials."""

from __future__ import annotations

import logging
import asyncio
import os
from hashlib import sha256
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

import httpx

from app.errors import UserError
from app.runtime_paths import RuntimePaths

logger = logging.getLogger(__name__)

CREDENTIAL_SERVICE_NAME = "heetkit"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEEPSEEK_MODELS_URL = "https://api.deepseek.com/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
MAX_CREDENTIAL_LENGTH = 8_192


class CredentialName(StrEnum):
    GEMINI_API_KEY = "gemini_api_key"
    TWITCH_CLIENT_SECRET = "twitch_client_secret"
    DEEPSEEK_API_KEY = "deepseek_api_key"
    OPENAI_API_KEY = "openai_api_key"


CREDENTIAL_LABELS = {
    CredentialName.GEMINI_API_KEY: "Gemini API key",
    CredentialName.TWITCH_CLIENT_SECRET: "Twitch client secret",
    CredentialName.DEEPSEEK_API_KEY: "DeepSeek API key",
    CredentialName.OPENAI_API_KEY: "OpenAI API key",
}


class CredentialError(UserError, RuntimeError):
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

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        # Headless reuses validation without requiring the optional desktop backend.
        import keyring
        from keyring.errors import KeyringError, PasswordDeleteError
        self._keyring_error = KeyringError
        self._delete_error = PasswordDeleteError
        self._backend = backend if backend is not None else keyring
        paths = RuntimePaths.default()
        self._service_name = CREDENTIAL_SERVICE_NAME
        if not paths.is_default_profile:
            identity = sha256(os.path.normcase(str(paths.root.resolve())).encode("utf-8")).hexdigest()
            self._service_name += ":" + identity

    def get(self, name: CredentialName) -> str | None:
        try:
            value = self._backend.get_password(self._service_name, name.value)
        except self._keyring_error as error:
            raise CredentialError("credentials.secure_credential_storage_unavailable") from error
        return value or None

    def replace(self, name: CredentialName, value: str) -> None:
        try:
            self._backend.set_password(self._service_name, name.value, value)
        except self._keyring_error as error:
            raise CredentialError("credentials.could_not_store_credential_securely") from error

    def remove(self, name: CredentialName) -> bool:
        if self.get(name) is None:
            return False
        try:
            self._backend.delete_password(self._service_name, name.value)
        except self._delete_error:
            return False
        except self._keyring_error as error:
            raise CredentialError("credentials.could_not_remove_stored_credential") from error
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
            raise UserError("credentials.unknown_credential")
        try:
            return CredentialName(name)
        except ValueError as error:
            raise UserError("credentials.unknown_credential") from error

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
            raise UserError("credentials.credential_must_be_text")
        normalized = value.strip()
        if not normalized:
            raise UserError("credentials.credential_not_empty")
        if len(normalized) > MAX_CREDENTIAL_LENGTH:
            raise UserError("credentials.credential_must_not_exceed_characters", value1=str(MAX_CREDENTIAL_LENGTH))
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
            raise CredentialError("credentials.credential_not_configured")

        try:
            if parsed_name in {CredentialName.DEEPSEEK_API_KEY, CredentialName.OPENAI_API_KEY}:
                # A models probe verifies authentication only, never generation/tool access.
                async with asyncio.timeout(15):
                    url = OPENAI_MODELS_URL if parsed_name is CredentialName.OPENAI_API_KEY else DEEPSEEK_MODELS_URL
                    async with http_client.stream("GET", url,
                            headers={"Authorization": "Bearer " + value}, timeout=10) as response:
                        pass  # Do not read or log a credential-test response body.
            elif parsed_name is CredentialName.GEMINI_API_KEY:
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
        except (httpx.RequestError, TimeoutError, ValueError):
            # Header validation can include the supplied secret in its exception.
            raise CredentialError("credentials.credential_service_could_not_reached_rejected") from None

        if 200 <= response.status_code < 300:
            return
        if response.status_code in {400, 401, 403}:
            raise CredentialError("credentials.credential_rejected_by_provider")
        raise CredentialError("credentials.credential_could_not_verified_by_provider")
