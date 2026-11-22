"""Shared bounded HTTP transport and model discovery for HTTP AI providers."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from pydantic import SecretStr

from app.config.ai_models import validate_provider_model_id
from app.config.settings import Settings
from app.services.ai_provider import AIProviderSettings


class _ProviderHTTPError(RuntimeError):
    def __init__(self, provider: str, status_code: int, model_not_found: bool = False):
        super().__init__(f"{provider} returned HTTP {status_code}.")
        self.status_code = status_code
        self.model_not_found = model_not_found


class _SearchError(RuntimeError):
    """Search failed to establish usable context; never render its payload."""


class HTTPProvider:
    """Snapshot flat settings and drain active operations before closing."""

    name: str
    settings_prefix: str
    base_url: str
    transport_timeout: float
    model_defaults: tuple[str, str] | None = None
    default_thinking = "default"
    strict_secret_key = True
    read_error_body = True
    discovery_timeout = 15.0
    discovery_transport_timeout = 10.0
    max_response_bytes = 1024 * 1024
    max_discovered_models = 200
    max_model_id_length = 200
    model_id_pattern = None

    def __init__(self, settings: Settings):
        self.settings = settings
        self._closed = False
        self._active_calls = 0
        self._condition = asyncio.Condition()

    def snapshot(self) -> AIProviderSettings:
        prefix = self.settings_prefix
        model = (getattr(self.settings, prefix + "_model") if self.model_defaults is None
                 else getattr(self.settings, prefix + "_model", self.model_defaults[0]))
        fallback = (getattr(self.settings, prefix + "_fallback_model") if self.model_defaults is None
                    else getattr(self.settings, prefix + "_fallback_model", self.model_defaults[1]))
        return AIProviderSettings(
            model=model,
            fallback_model=fallback,
            api_key=getattr(self.settings, prefix + "_api_key", None),
            thinking=getattr(self.settings, prefix + "_thinking", self.default_thinking),
        )

    @property
    def is_available(self) -> bool:
        return self._available_with_key(getattr(self.settings, self.settings_prefix + "_api_key", None))

    def _available_with_key(self, key: SecretStr | None) -> bool:
        return (not self._closed and key is not None
                and (not self.strict_secret_key or isinstance(key, SecretStr))
                and bool(key.get_secret_value().strip()))

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        async with self._condition:
            if self._closed:
                raise RuntimeError(f"{self.name} service has shut down.")
            self._active_calls += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_calls -= 1
                self._condition.notify_all()

    async def aclose(self) -> None:
        async with self._condition:
            self._closed = True
            await self._condition.wait_for(lambda: self._active_calls == 0)

    async def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self.max_response_bytes:
                raise ValueError(f"{self.name} response exceeded the size limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _http_json(
        self, method: str, path: str, key: SecretStr, **kwargs: Any,
    ) -> tuple[int, Any]:
        transport_timeout = kwargs.pop("transport_timeout", self.transport_timeout)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(transport_timeout),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                method, path,
                headers={"Authorization": f"Bearer {key.get_secret_value()}",
                         "Content-Type": "application/json"},
                **kwargs,
            ) as response:
                if response.status_code >= 400 and not self.read_error_body:
                    return response.status_code, None
                raw = await self._read_limited(response)
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    if response.status_code >= 400:
                        payload = None
                    else:
                        raise
                return response.status_code, payload

    def _response_error_is_model_missing(self, payload: Any) -> bool:
        return True

    def _http_error(self, status: int, payload: Any = None) -> _ProviderHTTPError:
        return _ProviderHTTPError(self.name, status, self._response_error_is_model_missing(payload))

    async def discover_models(self) -> list[str]:
        options = self.snapshot()
        if not self._available_with_key(options.api_key):
            raise RuntimeError(f"{self.name} API key is not configured.")
        assert options.api_key is not None
        async with self._operation():
            async with asyncio.timeout(self.discovery_timeout):
                status, payload = await self._http_json(
                    "GET", "/models", options.api_key,
                    transport_timeout=self.discovery_transport_timeout,
                )
        if status >= 400:
            raise self._http_error(status)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError(f"{self.name} model discovery returned an invalid response.")
        models = {
            model_id for item in data[:self.max_discovered_models]
            if isinstance(item, dict)
            and (model_id := self._normalize_model_id(item.get("id"))) is not None
        }
        return sorted(models)

    def _normalize_model_id(self, value: object) -> str | None:
        if (not isinstance(value, str) or len(value) > self.max_model_id_length
                or (self.model_id_pattern is not None and not self.model_id_pattern.fullmatch(value))):
            return None
        try:
            return validate_provider_model_id(self.settings_prefix, value)
        except ValueError:
            return None
