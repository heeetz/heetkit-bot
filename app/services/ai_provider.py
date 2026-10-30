"""Internal provider seam; command handlers continue to use AIService/AIReply."""

from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import SecretStr


USAGE_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "tool_input_tokens",
                "reasoning_tokens", "search_requests")


def usage_count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def normalized_usage(provider: str, payload: object) -> dict[str, int | bool]:
    """Only numeric billing metadata; cache/reasoning are subsets of token totals."""
    def get(value, name):
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

    usage = get(payload, "usage_metadata" if provider == "gemini" else "usage")
    fields = {}
    mapping = ({"input_tokens": "prompt_token_count", "output_tokens": "candidates_token_count",
                "total_tokens": "total_token_count", "cached_input_tokens": "cached_content_token_count",
                "reasoning_tokens": "thoughts_token_count", "tool_input_tokens": "tool_use_prompt_token_count"} if provider == "gemini" else
               {"input_tokens": "prompt_tokens", "output_tokens": "completion_tokens",
                "total_tokens": "total_tokens", "cached_input_tokens": "prompt_cache_hit_tokens"}
               if provider == "deepseek" else
               {"input_tokens": "input_tokens", "output_tokens": "output_tokens", "total_tokens": "total_tokens"})
    for target, source in mapping.items():
        count = usage_count(get(usage, source))
        if count is not None:
            fields[target] = count
    if provider in {"openai", "deepseek"}:
        details = get(usage, "output_tokens_details" if provider == "openai" else "completion_tokens_details")
        reasoning = usage_count(get(details, "reasoning_tokens"))
        if reasoning is not None:
            fields["reasoning_tokens"] = reasoning
        if provider == "openai":
            cached = usage_count(get(get(usage, "input_tokens_details"), "cached_tokens"))
            if cached is not None:
                fields["cached_input_tokens"] = cached
        elif "cached_input_tokens" not in fields:
            cached = usage_count(get(get(usage, "prompt_tokens_details"), "cached_tokens"))
            if cached is not None:
                fields["cached_input_tokens"] = cached
    if provider == "gemini" and "output_tokens" in fields and "reasoning_tokens" in fields:
        # Gemini candidates exclude thoughts; other providers' output includes them.
        fields["output_tokens"] = min(2**63 - 1, fields["output_tokens"] + fields["reasoning_tokens"])
    if provider == "gemini" and "input_tokens" in fields and "tool_input_tokens" in fields:
        fields["input_tokens"] = min(2**63 - 1, fields["input_tokens"] + fields["tool_input_tokens"])
    fields["usage_incomplete"] = ("input_tokens" not in fields or "output_tokens" not in fields
                                   or (provider == "gemini" and "reasoning_tokens" not in fields))
    if all(key in fields for key in ("input_tokens", "output_tokens", "total_tokens")):
        fields["usage_incomplete"] |= fields["input_tokens"] + fields["output_tokens"] != fields["total_tokens"]
    return fields


@dataclass(slots=True)
class UsageAccumulator:
    """Bounded per-attempt totals across tool continuations, never provider payloads."""

    values: dict[str, int | bool] = field(default_factory=dict)
    rounds: int = 0

    def add(self, values: dict[str, int | bool]) -> None:
        inconsistent = self.rounds > 0 and any(
            (key in self.values) != (usage_count(values.get(key)) is not None)
            for key in USAGE_FIELDS if key != "search_requests"
        )
        self.rounds += 1
        for key in USAGE_FIELDS:
            count = usage_count(values.get(key))
            if count is not None:
                self.values[key] = min(2**63 - 1, int(self.values.get(key, 0)) + count)
        self.values["usage_incomplete"] = bool(inconsistent or self.values.get("usage_incomplete")
                                                or values.get("usage_incomplete"))

    def metadata(self) -> dict:
        return {**self.values, "usage_incomplete": bool(not self.rounds or self.values.get("usage_incomplete"))}


_attempt_usage: ContextVar[UsageAccumulator | None] = ContextVar("ai_attempt_usage", default=None)


@contextmanager
def attempt_usage():
    usage = UsageAccumulator()
    token = _attempt_usage.set(usage)
    try:
        yield usage
    finally:
        _attempt_usage.reset(token)


def report_usage(provider: str, payload: object) -> None:
    usage = _attempt_usage.get()
    if usage is not None:
        usage.add(normalized_usage(provider, payload))


def report_search_request() -> None:
    usage = _attempt_usage.get()
    if usage is not None:
        usage.values["search_requests"] = int(usage.values.get("search_requests", 0)) + 1


class AIModelDiscoveryError(RuntimeError):
    """Application-owned diagnostics; never render provider errors or bodies."""

    def __init__(self, code: str):
        messages = {
            "provider_unavailable": "Configure the provider API key and ensure its adapter is available before discovering models.",
            "credential_rejected": "The provider rejected the configured key.",
            "rate_limited": "Model discovery was rate limited. Try again later.",
            "timeout": "Model discovery timed out. Try again later.",
            "provider_error": "Could not discover models from the provider.",
            "credentials_changed": "Credentials changed during discovery. Discover models again with the current connection.",
        }
        self.code = code if code in messages else "provider_error"
        super().__init__(messages[self.code])


@dataclass(frozen=True, slots=True)
class AIProviderCapabilities:
    search: bool = False


@dataclass(frozen=True, slots=True)
class AIProviderSettings:
    """Capture model choices and the credential before any asynchronous work."""

    model: str
    fallback_model: str
    api_key: SecretStr | None = field(default=None, repr=False)
    thinking: str = "default"
    single_attempt: bool = False


@dataclass(frozen=True, slots=True)
class AIGenerationRequest:
    system_instruction: str = field(repr=False)
    content: str = field(repr=False)
    use_search: bool = False


@dataclass(frozen=True, slots=True)
class AISource:
    """Bounded attribution metadata; never page text, tool arguments or reasoning."""

    title: str
    url: str


def source_metadata(title: object, url: object) -> AISource | None:
    if (not isinstance(url, str) or len(url) > 2048
            or any(not c.isprintable() or c.isspace() for c in url)):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        parsed.port  # Reject malformed ports without retaining parser diagnostics.
    except ValueError:
        return None
    label = (" ".join("".join(c for c in title if c.isprintable() or c.isspace()).split())[:200]
             if isinstance(title, str) else parsed.hostname)
    return AISource(title=label or parsed.hostname, url=url)


@dataclass(frozen=True, slots=True)
class AIProviderResponse:
    text: str = field(default="", repr=False)
    status: Literal["success", "provider_unavailable", "model_unavailable", "configuration_error",
                    "search_error", "api_error", "timeout"] = "success"
    safety_blocked: bool = False
    sources: tuple[AISource, ...] = ()
    search_used: bool = False
    attribution_required: bool = False
    effective_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    tool_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    search_requests: int | None = None
    usage_incomplete: bool = True
    inline_citations: bool = False


class AIProvider(Protocol):
    name: str
    capabilities: AIProviderCapabilities

    @property
    def is_available(self) -> bool: ...

    def snapshot(self) -> AIProviderSettings: ...

    async def generate(
        self, request: AIGenerationRequest, options: AIProviderSettings,
    ) -> AIProviderResponse: ...

    async def discover_models(self) -> list[str]: ...

    async def aclose(self) -> None: ...
