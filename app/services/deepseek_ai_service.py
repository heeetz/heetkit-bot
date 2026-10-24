"""HTTPX adapter for DeepSeek chat completions and model discovery."""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from pydantic import SecretStr

from app.config.settings import Settings
from app.config.ai_models import validate_provider_model_id
from app.services.ai_provider import (
    AIGenerationRequest, AIProviderCapabilities, AIProviderResponse, AIProviderSettings,
)
from app.utils.logging import operator_event, operator_event_scope

logger = logging.getLogger(__name__)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_REQUEST_TIMEOUT_SECONDS = 60.0
DEEPSEEK_TRANSPORT_TIMEOUT_SECONDS = 45.0
DEEPSEEK_DISCOVERY_TIMEOUT_SECONDS = 15.0
DEEPSEEK_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS = 10.0
DEEPSEEK_MAX_RESPONSE_BYTES = 1024 * 1024
DEEPSEEK_MAX_DISCOVERED_MODELS = 200
DEEPSEEK_MAX_TOKENS = 1024


class _ProviderHTTPError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"DeepSeek returned HTTP {status_code}.")
        self.status_code = status_code


class DeepSeekProvider:
    """Send prepared prompts to DeepSeek without owning prompt/output policy."""

    name = "DeepSeek"
    capabilities = AIProviderCapabilities(search=False)

    def __init__(self, settings: Settings):
        self.settings = settings
        self._closed = False
        self._active_calls = 0
        self._condition = asyncio.Condition()

    def snapshot(self) -> AIProviderSettings:
        return AIProviderSettings(
            model=self.settings.deepseek_model,
            fallback_model=self.settings.deepseek_fallback_model,
            api_key=getattr(self.settings, "deepseek_api_key", None),
        )

    @property
    def is_available(self) -> bool:
        return self._available_with_key(getattr(self.settings, "deepseek_api_key", None))

    def _available_with_key(self, key: SecretStr | None) -> bool:
        return not self._closed and key is not None and bool(key.get_secret_value().strip())

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        async with self._condition:
            if self._closed:
                raise RuntimeError("DeepSeek service has shut down.")
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
            if size > DEEPSEEK_MAX_RESPONSE_BYTES:
                raise ValueError("DeepSeek response exceeded the size limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _http_json(
        self, method: str, path: str, key: SecretStr, *,
        transport_timeout: float = DEEPSEEK_TRANSPORT_TIMEOUT_SECONDS, **kwargs: Any,
    ) -> tuple[int, Any]:
        timeout = httpx.Timeout(transport_timeout)
        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                method,
                path,
                headers={"Authorization": f"Bearer {key.get_secret_value()}",
                         "Content-Type": "application/json"},
                **kwargs,
            ) as response:
                if response.status_code >= 400:
                    return response.status_code, None
                raw = await self._read_limited(response)
                return response.status_code, json.loads(raw)

    async def discover_models(self) -> list[str]:
        options = self.snapshot()
        if not self._available_with_key(options.api_key):
            raise RuntimeError("DeepSeek API key is not configured.")
        assert options.api_key is not None
        async with self._operation():
            async with asyncio.timeout(DEEPSEEK_DISCOVERY_TIMEOUT_SECONDS):
                status, payload = await self._http_json(
                    "GET", "/models", options.api_key,
                    transport_timeout=DEEPSEEK_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS,
                )
        if status >= 400:
            raise _ProviderHTTPError(status)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("DeepSeek model discovery returned an invalid response.")
        models = {
            model_id for item in data[:DEEPSEEK_MAX_DISCOVERED_MODELS]
            if isinstance(item, dict)
            and (model_id := self._normalize_model_id(item.get("id"))) is not None
        }
        return sorted(models)

    @staticmethod
    def _normalize_model_id(value: object) -> str | None:
        if not isinstance(value, str) or len(value) > 128:
            return None
        try:
            return validate_provider_model_id("deepseek", value)
        except ValueError:
            return None

    async def _generate_model(
        self, request: AIGenerationRequest, model: str, key: SecretStr,
    ) -> tuple[dict[str, Any], int]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.content},
            ],
            "thinking": {"type": "disabled"},
            "stream": False,
            "max_tokens": DEEPSEEK_MAX_TOKENS,
        }
        status, result = await self._http_json(
            "POST", "/chat/completions", key, json=payload,
        )
        if status >= 400:
            raise _ProviderHTTPError(status)
        if not isinstance(result, dict):
            raise ValueError("DeepSeek response was not an object.")
        return result, status

    async def generate(
        self, request: AIGenerationRequest, options: AIProviderSettings,
    ) -> AIProviderResponse:
        if request.use_search or not self._available_with_key(options.api_key):
            return AIProviderResponse(status="provider_unavailable")
        assert options.api_key is not None
        try:
            async with self._operation():
                async with asyncio.timeout(DEEPSEEK_REQUEST_TIMEOUT_SECONDS):
                    for attempt, model in enumerate((options.model, options.fallback_model), start=1):
                        with operator_event_scope(requested_provider=self.name,
                                                  requested_model=options.model,
                                                  provider=self.name, model=model,
                                                  attempt=attempt, fallback=attempt > 1):
                            started = time.monotonic()
                            operator_event(logger, "ai.request_start", "attempt")
                            outcome = "provider_failure"
                            usage: dict[str, int] = {}
                            try:
                                result, _ = await self._generate_model(request, model, options.api_key)
                                usage_data = result.get("usage")
                                if isinstance(usage_data, dict):
                                    for source, target in (("prompt_tokens", "input_tokens"),
                                                           ("completion_tokens", "output_tokens"),
                                                           ("total_tokens", "total_tokens")):
                                        count = usage_data.get(source)
                                        if type(count) is int and 0 <= count <= 2**63 - 1:
                                            usage[target] = count
                                choices = result.get("choices")
                                choice = choices[0] if isinstance(choices, list) and choices else None
                                message = choice.get("message") if isinstance(choice, dict) else None
                                content = message.get("content") if isinstance(message, dict) else None
                                finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
                                if finish_reason != "stop" or not isinstance(content, str) or not content.strip():
                                    outcome = "invalid_response"
                                    return AIProviderResponse(status="api_error")
                                outcome = "generated"
                                return AIProviderResponse(text=content)
                            except asyncio.CancelledError:
                                outcome = "cancelled"
                                raise
                            except _ProviderHTTPError as error:
                                if (attempt == 1 and error.status_code == 404
                                        and options.fallback_model != options.model):
                                    operator_event(logger, "ai.fallback", "model_unavailable")
                                    continue
                                raise
                            finally:
                                operator_event(logger, "ai.request_finish", outcome,
                                               duration_seconds=round(time.monotonic() - started, 3), **usage)
            return AIProviderResponse(status="api_error")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            operator_event(logger, "ai.failure", "provider_failure", reason=type(error).__name__)
            status = "timeout" if isinstance(error, (TimeoutError, httpx.TimeoutException)) else "api_error"
            return AIProviderResponse(status=status)
