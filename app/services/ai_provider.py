"""Internal provider seam; command handlers continue to use AIService/AIReply."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import SecretStr


@dataclass(frozen=True, slots=True)
class AIProviderCapabilities:
    search: bool = False


@dataclass(frozen=True, slots=True)
class AIProviderSettings:
    """Capture model choices and the credential before any asynchronous work."""

    model: str
    fallback_model: str
    api_key: SecretStr | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class AIGenerationRequest:
    system_instruction: str = field(repr=False)
    content: str = field(repr=False)
    use_search: bool = False


@dataclass(frozen=True, slots=True)
class AIProviderResponse:
    text: str = field(default="", repr=False)
    status: Literal["success", "provider_unavailable", "api_error", "timeout"] = "success"
    safety_blocked: bool = False


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
