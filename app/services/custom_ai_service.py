"""One operator-defined OpenAI-compatible endpoint (for example LM Studio) via chat completions."""

import asyncio
import logging
import re
import time

import httpx

from app.config.ai_capabilities import validate_model_options
from app.config.settings import ai_connection, ai_connection_key
from app.services.custom_ai_network import custom_transport, effective_policy
from app.services.ai_provider import (
    AIGenerationRequest, AIProviderCapabilities, AIProviderResponse, AIProviderSettings,
    attempt_usage, report_usage,
)
from app.services.http_provider import HTTPProvider, _ProviderHTTPError
from app.utils.logging import operator_event, operator_event_scope

logger = logging.getLogger(__name__)
CUSTOM_TRANSPORT_TIMEOUT_SECONDS = 55.0
# Room for local reasoning models; the reply itself is cut to the answer limit.
CUSTOM_MAX_TOKENS = 4096
# Reasoning that a server leaves inside the answer text; an unclosed block runs to the end.
_REASONING_BLOCK = re.compile(r"<(think|thinking|reasoning)>.*?(?:</\1>|\Z)", re.IGNORECASE | re.DOTALL)


def final_answer(content: object) -> str | None:
    """Answer text without recognized reasoning blocks; None when nothing else remains."""
    if not isinstance(content, str):
        return None
    text = _REASONING_BLOCK.sub("", content).strip()
    return text or None


class CustomProvider(HTTPProvider):
    """Send prepared prompts to the configured endpoint; the key is optional."""

    name = "Custom"
    capabilities = AIProviderCapabilities(search=False)
    settings_prefix = "custom"
    base_url = ""
    transport_timeout = CUSTOM_TRANSPORT_TIMEOUT_SECONDS
    model_defaults = ("", "")

    def _transport(self, base_url: str) -> httpx.AsyncBaseTransport | None:
        connection = ai_connection(self.settings, self.connection_id)
        return custom_transport(effective_policy(self.settings.custom_ai_network,
                                                 bool(connection and connection.private_network)), base_url)

    def snapshot(self) -> AIProviderSettings:
        key = ai_connection_key(self.settings, self.connection_id)
        connection = ai_connection(self.settings, self.connection_id)
        return AIProviderSettings(model="", fallback_model="", base_url=connection.base_url if connection else None,
                                  api_key=key if key is not None and key.get_secret_value().strip() else None)

    @property
    def is_available(self) -> bool:
        return self._available_with(self.snapshot())

    def _available_with(self, options: AIProviderSettings) -> bool:
        return not self._closed and bool(options.base_url)

    async def generate(self, request: AIGenerationRequest, options: AIProviderSettings) -> AIProviderResponse:
        if not self._available_with(options):
            return AIProviderResponse(status="provider_unavailable")
        try:
            validate_model_options("custom", options.model, options.thinking, request.use_search)
        except ValueError:
            return AIProviderResponse(status="configuration_error")
        usage = None
        outcome = "provider_failure"
        try:
            async with self._operation():
                with operator_event_scope(provider=self.name, model=options.model), attempt_usage() as usage:
                    started = time.monotonic()
                    operator_event(logger, "ai.request_start", "attempt")
                    try:
                        status, result = await self._http_json("POST", "/chat/completions", options.api_key,
                            base_url=options.base_url, json={
                                "model": options.model,
                                "messages": [{"role": "system", "content": request.system_instruction},
                                             {"role": "user", "content": request.content}],
                                "stream": False,
                                "max_tokens": CUSTOM_MAX_TOKENS,
                            })
                        if status >= 300:
                            raise self._http_error(status)
                        report_usage("custom", result)
                        choices = result.get("choices") if isinstance(result, dict) else None
                        choice = choices[0] if isinstance(choices, list) and choices else None
                        message = choice.get("message") if isinstance(choice, dict) else None
                        # Separately reported reasoning (reasoning_content) is never read.
                        text = final_answer(message.get("content") if isinstance(message, dict) else None)
                        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
                        if finish_reason != "stop" or text is None:
                            outcome = "invalid_response"
                            return AIProviderResponse(status="api_error", **usage.metadata())
                        outcome = "generated"
                        return AIProviderResponse(text=text, **usage.metadata())
                    except asyncio.CancelledError:
                        outcome = "cancelled"
                        raise
                    finally:
                        operator_event(logger, "ai.request_finish", outcome,
                                       duration_seconds=round(time.monotonic() - started, 3), **usage.metadata())
        except asyncio.CancelledError:
            raise
        except Exception as error:
            operator_event(logger, "ai.failure", "provider_failure", reason=type(error).__name__)
            if isinstance(error, _ProviderHTTPError) and error.status_code == 404:
                status = "model_unavailable"
            else:
                status = "timeout" if isinstance(error, (TimeoutError, httpx.TimeoutException)) else "api_error"
            return AIProviderResponse(status=status, **(usage.metadata() if usage is not None else {}))
