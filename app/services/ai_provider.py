"""Internal provider seam; command handlers continue to use AIService/AIReply."""

from dataclasses import dataclass, field
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import SecretStr


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
