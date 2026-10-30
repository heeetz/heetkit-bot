"""Gemini SDK adapter: transport, model discovery, capabilities and client leases."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from pydantic import SecretStr

from app.config.settings import Settings
from app.config.ai_capabilities import native_thinking_parameters, validate_model_options
from app.services.ai_provider import (
    AIGenerationRequest, AIProviderCapabilities, AIProviderResponse, AIProviderSettings,
    AISource, source_metadata,
    normalized_usage,
)
from app.utils.logging import operator_event, operator_event_scope

logger = logging.getLogger(__name__)
GEMINI_REQUEST_TIMEOUT_SECONDS = 60.0
GEMINI_TRANSPORT_TIMEOUT_SECONDS = 45.0
GEMINI_DISCOVERY_TIMEOUT_SECONDS = 15.0
GEMINI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS = 10.0
GEMINI_CLOSE_TIMEOUT_SECONDS = 5.0
GEMINI_MAX_DISCOVERED_MODELS = 500
GEMINI_MAX_OUTPUT_TOKENS = 16384
_NON_CHAT_MODEL_MARKERS = (
    "embedding",
    "image",
    "live",
    "tts",
    "transcribe",
)


class GeminiProvider:
    """Translate prepared requests without owning shared prompts or output policy."""

    name = "Google Gemini"
    capabilities = AIProviderCapabilities(search=True)

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None
        self._client_key: object | None = None
        self._client_users: dict[Any, int] = {}
        self._retired_clients: set[Any] = set()
        self._client_condition = asyncio.Condition()
        self._closed = False

    def snapshot(self) -> AIProviderSettings:
        return AIProviderSettings(
            model=self.settings.gemini_model,
            fallback_model=self.settings.gemini_fallback_model,
            api_key=getattr(self.settings, "gemini_api_key", None),
            thinking=getattr(self.settings, "gemini_thinking", "default"),
        )

    @property
    def is_available(self) -> bool:
        return self._available_with_key(getattr(self.settings, "gemini_api_key", None))

    def _available_with_key(self, key: SecretStr | None) -> bool:
        if self._closed or key is None or not key.get_secret_value().strip():
            return False
        try:
            from google import genai
        except ImportError:
            return False
        return callable(getattr(genai, "Client", None))

    @staticmethod
    async def _close_client(client: Any) -> None:
        try:
            async with asyncio.timeout(GEMINI_CLOSE_TIMEOUT_SECONDS):
                await client.aio.aclose()
        finally:
            client.close()

    @asynccontextmanager
    async def _provider_client(self, api_key: SecretStr | None = None) -> AsyncIterator[Any]:
        """Lease the shared SDK client without closing an in-flight old-key request."""
        async with self._client_condition:
            if self._closed:
                raise RuntimeError("Gemini service has shut down.")
            key = api_key if api_key is not None else self.settings.gemini_api_key
            if key is None:
                raise RuntimeError("Gemini API key is not configured.")
            if self._client is None or self._client_key != key:
                from google import genai
                from google.genai import types

                # The pinned SDK uses cancellable async socket I/O (HTTPX or aiohttp),
                # not the uninterruptible Requests workers used by SDK 0.8.0.
                replacement = genai.Client(
                    vertexai=False,
                    api_key=key.get_secret_value(),
                    http_options=types.HttpOptions(
                        timeout=int(GEMINI_TRANSPORT_TIMEOUT_SECONDS * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
                previous = self._client
                self._client = replacement
                self._client_key = key
                self._client_users[replacement] = 0
                if previous is not None:
                    if self._client_users[previous]:
                        self._retired_clients.add(previous)
                    else:
                        del self._client_users[previous]
                        await self._close_client(previous)
            client = self._client
            self._client_users[client] += 1
        try:
            yield client.aio
        finally:
            async with self._client_condition:
                self._client_users[client] -= 1
                try:
                    if client in self._retired_clients and not self._client_users[client]:
                        self._retired_clients.remove(client)
                        del self._client_users[client]
                        await self._close_client(client)
                finally:
                    self._client_condition.notify_all()

    async def aclose(self) -> None:
        """Retire clients; active calls have total deadlines and close on release."""
        async with self._client_condition:
            self._closed = True
            self._client = None
            self._client_key = None
            # Retire before waiting so cancelled shutdown still leaves active leases
            # responsible for cleanup when they finish or are cancelled by the host.
            self._retired_clients.update(self._client_users)
            for client, users in list(self._client_users.items()):
                if not users:
                    self._retired_clients.remove(client)
                    del self._client_users[client]
                    await self._close_client(client)
            await self._client_condition.wait_for(lambda: not self._client_users)

    async def discover_models(self) -> list[str]:
        """Return provider models suitable for text generation with the configured key."""
        try:
            from google.genai import types

            async with self._provider_client() as client:
                # Bound the whole traversal as well as each page's socket I/O.
                async with asyncio.timeout(GEMINI_DISCOVERY_TIMEOUT_SECONDS):
                    pager = await client.models.list(config=types.ListModelsConfig(
                        http_options=types.HttpOptions(
                            timeout=int(GEMINI_DISCOVERY_TRANSPORT_TIMEOUT_SECONDS * 1000),
                        ),
                    ))
                    discovered: set[str] = set()
                    count = 0
                    async for model in pager:
                        count += 1
                        model_id = self._normalize_discovered_model(model)
                        if model_id is not None:
                            discovered.add(model_id)
                        if count >= GEMINI_MAX_DISCOVERED_MODELS:
                            break
        except ImportError as error:
            raise RuntimeError("google-genai package is not available.") from error
        return sorted(discovered)

    @staticmethod
    def _normalize_discovered_model(model: object) -> str | None:
        name = getattr(model, "name", None)
        actions = getattr(model, "supported_actions", None) or ()
        normalized_actions = {
            str(action).replace("_", "").lower()
            for action in actions
        }
        if not isinstance(name, str) or "generatecontent" not in normalized_actions:
            return None
        model_id = name.rsplit("/", 1)[-1]
        if not model_id.startswith("gemini-"):
            return None
        if any(marker in model_id.lower() for marker in _NON_CHAT_MODEL_MARKERS):
            return None
        return model_id

    async def _request_with_model_fallback(
        self,
        request: Callable[[str], Awaitable[Any]],
        options: AIProviderSettings,
    ) -> tuple[Any, str]:
        selected_model = options.model
        fallback_model = options.fallback_model
        models = (selected_model,) if options.single_attempt else (selected_model, fallback_model)
        for attempt, model in enumerate(models, start=1):
            context = {"provider": "Google Gemini", "model": model}
            if not options.single_attempt:
                context.update(requested_provider="Google Gemini", requested_model=selected_model,
                               attempt=attempt, fallback=attempt > 1)
            with operator_event_scope(**context):
                started = time.monotonic()
                operator_event(logger, "ai.request_start", "attempt")
                outcome = "provider_failure"
                usage = {"usage_incomplete": True}
                try:
                    response = await request(model)
                    # Only aggregate usage counts; never serialize provider payloads
                    # or thought/reasoning parts, even when the SDK exposes them.
                    usage = normalized_usage("gemini", response)
                    outcome = "generated"
                    return response, model
                except asyncio.CancelledError:
                    outcome = "cancelled"
                    raise
                except Exception as error:
                    # Some SDK failures report numeric usage even without an answer.
                    usage = normalized_usage("gemini", error)
                    if (options.single_attempt or attempt != 1 or getattr(error, "code", None) != 404
                            or fallback_model == selected_model):
                        raise
                    operator_event(logger, "ai.fallback", "model_unavailable")
                finally:
                    operator_event(logger, "ai.request_finish", outcome,
                                   duration_seconds=round(time.monotonic() - started, 3), **usage)
        raise RuntimeError("No AI model attempt completed.")

    async def generate(
        self, request: AIGenerationRequest, options: AIProviderSettings,
    ) -> AIProviderResponse:
        if not self._available_with_key(options.api_key):
            return AIProviderResponse(status="provider_unavailable")
        try:
            validate_model_options("gemini", options.model, options.thinking, request.use_search)
        except ValueError:
            return AIProviderResponse(status="configuration_error")
        try:
            from google.genai import types

            content = request.content
            if request.use_search:
                content = (
                    "Use Google Search to verify current, changing, or event-related facts before answering.\n\n"
                    + content
                )
            async def request_model(model: str) -> Any:
                validate_model_options("gemini", model, options.thinking, request.use_search)
                thinking = native_thinking_parameters("gemini", model, options.thinking)
                budget = thinking.get("thinking_budget", 0)
                # Budgets are guidance; the total generation cap bounds thinking plus
                # final output. Reserve final-answer room even at a native maximum.
                output_limit = max(GEMINI_MAX_OUTPUT_TOKENS, budget + 1024)
                config = types.GenerateContentConfig(
                    system_instruction=request.system_instruction,
                    tools=[types.Tool(google_search=types.GoogleSearch())] if request.use_search else None,
                    thinking_config=types.ThinkingConfig(**thinking) if thinking else None,
                    max_output_tokens=output_limit,
                )
                return await client.models.generate_content(model=model, contents=content, config=config)

            async with self._provider_client(options.api_key) as client:
                async with asyncio.timeout(GEMINI_REQUEST_TIMEOUT_SECONDS):
                    response, _ = await self._request_with_model_fallback(request_model, options)
            usage = normalized_usage("gemini", response)

            candidates = getattr(response, "candidates", None) or []
            grounding_metadata = [
                getattr(candidate, "grounding_metadata", None)
                for candidate in candidates
            ]
            search_queries = sum(
                len(getattr(metadata, "web_search_queries", None) or [])
                for metadata in grounding_metadata
                if metadata is not None
            )
            grounding_chunks = sum(
                len(getattr(metadata, "grounding_chunks", None) or [])
                for metadata in grounding_metadata
                if metadata is not None
            )
            tool_call_parts = sum(
                sum(
                    1
                    for part in (getattr(candidate.content, "parts", None) or [])
                    if getattr(part, "function_call", None) is not None
                    or getattr(part, "tool_call", None) is not None
                )
                for candidate in candidates
                if getattr(candidate, "content", None) is not None
            )
            afc_history = getattr(response, "automatic_function_calling_history", None) or []
            logger.info(
                "Gemini response diagnostics candidates=%d tool_call_parts=%d "
                "grounding_metadata=%s search_queries=%d grounding_chunks=%d afc_history=%d",
                len(candidates),
                tool_call_parts,
                any(metadata is not None for metadata in grounding_metadata),
                search_queries,
                grounding_chunks,
                len(afc_history),
            )

            # Provider safety metadata also applies to any partial text.
            safety_reasons = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
            feedback = getattr(response, "prompt_feedback", None)
            block_reason = getattr(feedback, "block_reason", None)
            safety_blocked = bool(
                block_reason and str(block_reason).rsplit(".", 1)[-1] != "BLOCK_REASON_UNSPECIFIED"
            ) or any(
                str(getattr(candidate, "finish_reason", "")).rsplit(".", 1)[-1] in safety_reasons
                for candidate in candidates
            )
            if safety_blocked:
                return AIProviderResponse(safety_blocked=True, **usage)
            # Never trust a convenience accessor to decide which parts are thoughts.
            # Candidates are the provider's canonical final-answer surface.
            text = ""
            if candidates:
                candidate = candidates[0]
                finish = str(getattr(candidate, "finish_reason", "")).rsplit(".", 1)[-1]
                if finish in {"MAX_TOKENS", "MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "OTHER"}:
                    return AIProviderResponse(status="api_error", **usage)
                parts = getattr(getattr(candidate, "content", None), "parts", None) or []
                text = "".join(part.text for part in parts
                               if not getattr(part, "thought", False)
                               and isinstance(getattr(part, "text", None), str))
            else:
                # Minimal adapter fakes and SDK responses without candidate objects.
                value = getattr(response, "text", None)
                text = value if isinstance(value, str) else ""
            if not text.strip():
                return AIProviderResponse(status="api_error", **usage)
            sources: dict[str, AISource] = {}
            attribution_required = False
            for metadata in grounding_metadata:
                if metadata is None:
                    continue
                entry = getattr(metadata, "search_entry_point", None)
                attribution_required |= bool(getattr(entry, "rendered_content", None))
                for chunk in (getattr(metadata, "grounding_chunks", None) or [])[:20]:
                    web = getattr(chunk, "web", None)
                    source = source_metadata(getattr(web, "title", None), getattr(web, "uri", None))
                    if source is not None:
                        sources[source.url] = source
            search_used = bool(search_queries or grounding_chunks or attribution_required)
            return AIProviderResponse(
                text=text, sources=tuple(sources.values()), search_used=search_used,
                # Google requires a Suggestions display for grounded responses; URL
                # citations alone are insufficient for a plain-text chat transport.
                attribution_required=search_used,
                **usage,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            operator_event(logger, "ai.failure", "provider_failure", reason=type(error).__name__)
            if getattr(error, "code", None) == 404:
                status = "model_unavailable"
            elif isinstance(error, ValueError):
                status = "configuration_error"
            else:
                status = "timeout" if isinstance(error, (TimeoutError, httpx.TimeoutException)) else "api_error"
            return AIProviderResponse(status=status)
