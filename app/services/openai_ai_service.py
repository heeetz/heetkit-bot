"""HTTPX adapter for OpenAI Responses and model discovery."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from pydantic import SecretStr

from app.config.ai_capabilities import native_thinking_parameters, validate_model_options
from app.config.ai_models import DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_FALLBACK_MODEL, validate_provider_model_id
from app.config.settings import Settings
from app.services.ai_provider import (
    AIGenerationRequest,
    AIProviderCapabilities,
    AIProviderResponse,
    AIProviderSettings,
    AISource,
    source_metadata,
)
from app.utils.logging import operator_event, operator_event_scope

logger = logging.getLogger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_TRANSPORT_TIMEOUT_SECONDS = 55.0
OPENAI_DISCOVERY_TIMEOUT_SECONDS = 15.0
OPENAI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS = 10.0
OPENAI_MAX_RESPONSE_BYTES = 1024 * 1024
OPENAI_MAX_DISCOVERED_MODELS = 200
OPENAI_MAX_SOURCES = 20
OPENAI_MAX_TOOL_CALLS = 2
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class _ProviderHTTPError(RuntimeError):
    def __init__(self, status_code: int, model_not_found: bool = False):
        super().__init__(f"OpenAI returned HTTP {status_code}.")
        self.status_code = status_code
        self.model_not_found = model_not_found


class _SearchError(RuntimeError):
    """Search failed to establish usable, attributable context."""


class OpenAIProvider:
    """Send prepared instructions to OpenAI without owning prompt/output policy."""

    name = "OpenAI"
    capabilities = AIProviderCapabilities(search=True)

    def __init__(self, settings: Settings):
        self.settings = settings
        self._closed = False
        self._active_calls = 0
        self._condition = asyncio.Condition()

    def snapshot(self) -> AIProviderSettings:
        return AIProviderSettings(
            model=getattr(self.settings, "openai_model", DEFAULT_OPENAI_MODEL),
            fallback_model=getattr(self.settings, "openai_fallback_model", DEFAULT_OPENAI_FALLBACK_MODEL),
            api_key=getattr(self.settings, "openai_api_key", None),
            thinking=getattr(self.settings, "openai_thinking", "default"),
        )

    @property
    def is_available(self) -> bool:
        return self._available_with_key(getattr(self.settings, "openai_api_key", None))

    def _available_with_key(self, key: SecretStr | None) -> bool:
        return (not self._closed and isinstance(key, SecretStr)
                and bool(key.get_secret_value().strip()))

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        async with self._condition:
            if self._closed:
                raise RuntimeError("OpenAI service has shut down.")
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
            if size > OPENAI_MAX_RESPONSE_BYTES:
                raise ValueError("OpenAI response exceeded the size limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _http_json(
        self, method: str, path: str, key: SecretStr, *,
        transport_timeout: float = OPENAI_TRANSPORT_TIMEOUT_SECONDS, **kwargs: Any,
    ) -> tuple[int, Any]:
        async with httpx.AsyncClient(
            base_url=OPENAI_BASE_URL,
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
                raw = await self._read_limited(response)
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    if response.status_code >= 400:
                        payload = None
                    else:
                        raise
                return response.status_code, payload

    async def discover_models(self) -> list[str]:
        options = self.snapshot()
        if not self._available_with_key(options.api_key):
            raise RuntimeError("OpenAI API key is not configured.")
        assert options.api_key is not None
        async with self._operation():
            async with asyncio.timeout(OPENAI_DISCOVERY_TIMEOUT_SECONDS):
                status, payload = await self._http_json(
                    "GET", "/models", options.api_key,
                    transport_timeout=OPENAI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS,
                )
        if status >= 400:
            raise _ProviderHTTPError(status)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("OpenAI model discovery returned an invalid response.")
        models = {
            model_id for item in data[:OPENAI_MAX_DISCOVERED_MODELS]
            if isinstance(item, dict)
            and (model_id := self._normalize_model_id(item.get("id"))) is not None
        }
        return sorted(models)

    @staticmethod
    def _normalize_model_id(value: object) -> str | None:
        if not isinstance(value, str) or not _MODEL_ID.fullmatch(value):
            return None
        try:
            return validate_provider_model_id("openai", value)
        except ValueError:
            return None

    @staticmethod
    def _response_error_is_model_missing(payload: Any) -> bool:
        error = payload.get("error") if isinstance(payload, dict) else None
        return isinstance(error, dict) and error.get("code") == "model_not_found"

    def _parse_response(
        self, payload: Any, *, search_requested: bool,
    ) -> tuple[str, tuple[AISource, ...], bool, bool]:
        if not isinstance(payload, dict):
            raise ValueError("OpenAI response was not an object.")
        error = payload.get("error")
        incomplete = payload.get("incomplete_details")
        if ((isinstance(error, dict) and error.get("code") == "content_filter")
                or (isinstance(incomplete, dict) and incomplete.get("reason") == "content_filter")):
            return "", (), False, True
        status = payload.get("status")
        outputs = payload.get("output")
        if not isinstance(outputs, list):
            raise ValueError("OpenAI response output was invalid.")
        if status != "completed":
            # A provider refusal/content filter is a deliberate completed safety result.
            if status in {"failed", "incomplete", "queued", "in_progress", "cancelled"}:
                if any(isinstance(item, dict) and item.get("type") == "web_search_call"
                       for item in outputs):
                    raise _SearchError("OpenAI web search did not complete.")
                raise ValueError("OpenAI response did not complete.")
            raise ValueError("OpenAI response status was invalid.")

        search_calls = [item for item in outputs if isinstance(item, dict)
                        and item.get("type") == "web_search_call"]
        if search_calls and not search_requested:
            raise _SearchError("Unexpected web search call.")
        if len(search_calls) > OPENAI_MAX_TOOL_CALLS:
            raise _SearchError("OpenAI web search call limit was exceeded.")
        if any(item.get("status") != "completed" for item in search_calls):
            raise _SearchError("OpenAI web search did not complete.")
        search_used = bool(search_calls)

        if payload.get("incomplete_details"):
            if search_used:
                raise _SearchError("OpenAI response ended before search was completed.")
            raise ValueError("OpenAI response was incomplete.")

        text_parts: list[str] = []
        sources: dict[str, AISource] = {}
        safety_blocked = False
        for item in outputs:
            if not isinstance(item, dict):
                raise _SearchError("Malformed OpenAI output item.") if search_used else ValueError("Malformed output.")
            kind = item.get("type")
            if kind == "web_search_call":
                continue
            if kind in {"reasoning", "summary_text"}:
                continue
            if kind != "message" or item.get("role") != "assistant":
                raise _SearchError("Unexpected OpenAI output item.") if search_requested else ValueError("Unexpected output.")
            if item.get("status") not in (None, "completed"):
                raise _SearchError("OpenAI search answer was incomplete.") if search_used else ValueError("Incomplete message.")
            content = item.get("content")
            if not isinstance(content, list):
                raise _SearchError("Malformed OpenAI search answer.") if search_used else ValueError("Malformed message.")
            for block in content:
                if not isinstance(block, dict):
                    raise _SearchError("Malformed OpenAI search content.") if search_used else ValueError("Malformed content.")
                block_type = block.get("type")
                if block_type == "refusal":
                    safety_blocked = True
                    continue
                if block_type == "output_text":
                    value = block.get("text")
                    if not isinstance(value, str):
                        raise _SearchError("Malformed OpenAI search text.") if search_used else ValueError("Malformed text.")
                    annotations = block.get("annotations", [])
                    if not isinstance(annotations, list):
                        raise _SearchError("Malformed OpenAI citations.") if search_used else ValueError("Malformed citations.")
                    replacements: list[tuple[int, int, str]] = []
                    for annotation in annotations:
                        if not isinstance(annotation, dict):
                            raise _SearchError("Malformed OpenAI citation.") if search_used else ValueError("Malformed citation.")
                        if annotation.get("type") != "url_citation":
                            continue
                        source = source_metadata(annotation.get("title"), annotation.get("url"))
                        if source is None:
                            raise _SearchError("Invalid OpenAI citation.") if search_used else ValueError("Invalid citation.")
                        if source.url not in sources:
                            if len(sources) >= OPENAI_MAX_SOURCES:
                                raise _SearchError("OpenAI citation limit was exceeded.") if search_used else ValueError("Citation limit was exceeded.")
                            sources[source.url] = source
                        start = annotation.get("start_index")
                        end = annotation.get("end_index")
                        if (type(start) is not int or type(end) is not int or start < 0
                                or end <= start or end > len(value)):
                            raise _SearchError("Invalid OpenAI citation range.") if search_used else ValueError("Invalid citation range.")
                        annotated = value[start:end]
                        # An annotation can cover prose as well as a native citation
                        # marker. Keep the claim; only replace an actual marker.
                        label = "" if re.fullmatch(r"\ue200cite\ue202[^\ue201]*\ue201", annotated) else annotated
                        prefix = "" if not label and start > 0 and value[start - 1].isspace() else " "
                        suffix = " " if end < len(value) and not value[end].isspace() else ""
                        replacements.append((start, end, f"{label}{prefix}{source.url}{suffix}"))
                    replacements.sort()
                    if any(current[0] < previous[1]
                           for previous, current in zip(replacements, replacements[1:])):
                        raise _SearchError("Overlapping OpenAI citation ranges.") if search_used else ValueError("Overlapping citation ranges.")
                    visible_text = value
                    for start, end, replacement in reversed(replacements):
                        visible_text = visible_text[:start] + replacement + visible_text[end:]
                    text_parts.append(visible_text)
                elif block_type not in {"reasoning", "summary_text"}:
                    raise _SearchError("Unexpected OpenAI search content.") if search_used else ValueError("Unexpected content.")

        answer = "".join(text_parts).strip()
        if safety_blocked:
            return "", (), search_used, True
        if search_requested and not search_used:
            raise _SearchError("OpenAI did not complete the requested web search.")
        if not answer:
            raise _SearchError("OpenAI search returned no answer.") if search_used else ValueError("OpenAI returned no answer.")
        if search_used and not sources:
            raise _SearchError("OpenAI search returned no usable citations.")
        return answer, tuple(sources.values()), search_used, False

    async def _generate_model(
        self, request: AIGenerationRequest, model: str, options: AIProviderSettings,
    ) -> AIProviderResponse:
        assert options.api_key is not None
        payload: dict[str, Any] = {
            "model": model,
            "instructions": request.system_instruction,
            "input": request.content,
            "store": False,
            "max_output_tokens": 1024 if options.thinking == "none" else 4096,
            **native_thinking_parameters("openai", model, options.thinking),
        }
        if request.use_search:
            payload["instructions"] += (
                "\nUse web search for this answer. Keep the answer concise and leave room for visible source URLs. "
                "Use only completed web search results for current claims; never imply a search occurred if it did not."
            )
            payload["tools"] = [{"type": "web_search", "search_context_size": "low"}]
            payload["max_tool_calls"] = OPENAI_MAX_TOOL_CALLS
            payload["tool_choice"] = "required"
        status, result = await self._http_json("POST", "/responses", options.api_key, json=payload)
        if status >= 400:
            raise _ProviderHTTPError(status, self._response_error_is_model_missing(result))
        if not isinstance(result, dict):
            return AIProviderResponse(status="api_error")
        metadata = {
            "input_tokens": self._usage_count(result, "input_tokens"),
            "output_tokens": self._usage_count(result, "output_tokens"),
            "effective_model": self._effective_model(result, model),
        }
        try:
            text, sources, searched, safety_blocked = self._parse_response(
                result, search_requested=request.use_search,
            )
        except _SearchError:
            return AIProviderResponse(status="search_error", **metadata)
        except ValueError:
            return AIProviderResponse(status="api_error", **metadata)
        return AIProviderResponse(
            text=text, sources=sources, search_used=searched,
            safety_blocked=safety_blocked,
            inline_citations=searched,
            **metadata,
        )

    @staticmethod
    def _usage_count(payload: dict[str, Any], field: str) -> int | None:
        usage = payload.get("usage")
        count = usage.get(field) if isinstance(usage, dict) else None
        return count if type(count) is int and 0 <= count <= 2**63 - 1 else None

    @staticmethod
    def _effective_model(payload: dict[str, Any], requested: str) -> str:
        value = payload.get("model")
        return value if isinstance(value, str) and _MODEL_ID.fullmatch(value) else requested

    async def generate(
        self, request: AIGenerationRequest, options: AIProviderSettings,
    ) -> AIProviderResponse:
        if not self._available_with_key(options.api_key):
            return AIProviderResponse(status="provider_unavailable")
        try:
            validate_model_options("openai", options.model, options.thinking, request.use_search)
        except ValueError:
            return AIProviderResponse(status="configuration_error")
        assert options.api_key is not None
        try:
            async with self._operation():
                context = {"provider": self.name, "model": options.model}
                with operator_event_scope(**context):
                    started = time.monotonic()
                    operator_event(logger, "ai.request_start", "attempt")
                    outcome = "provider_failure"
                    usage: dict[str, int | str] = {}
                    try:
                        result = await self._generate_model(request, options.model, options)
                        outcome = (result.status if result.status != "success" else
                                   "safety_blocked" if result.safety_blocked else "generated")
                        if result.input_tokens is not None:
                            usage["input_tokens"] = result.input_tokens
                        if result.output_tokens is not None:
                            usage["output_tokens"] = result.output_tokens
                        if result.effective_model is not None:
                            usage["model"] = result.effective_model
                        return result
                    except _SearchError:
                        outcome = "search_failure"
                        return AIProviderResponse(status="search_error")
                    except _ProviderHTTPError as error:
                        outcome = "provider_http_error"
                        if error.status_code == 404 and error.model_not_found:
                            return AIProviderResponse(status="model_unavailable")
                        return AIProviderResponse(status="api_error")
                    except (TimeoutError, httpx.TimeoutException):
                        outcome = "timeout"
                        return AIProviderResponse(status="timeout")
                    except asyncio.CancelledError:
                        outcome = "cancelled"
                        raise
                    except Exception:
                        outcome = "provider_failure"
                        return AIProviderResponse(status="api_error")
                    finally:
                        operator_event(logger, "ai.request_finish", outcome,
                                       duration_seconds=round(time.monotonic() - started, 3), **usage)
        except asyncio.CancelledError:
            raise
        except RuntimeError:
            return AIProviderResponse(status="provider_unavailable")
