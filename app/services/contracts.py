"""Replaceable service contracts used by command handlers."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class AIGenerationDetails:
    """Safe effective options/outcomes, never credentials, reasoning or tool payloads."""

    provider: str
    model: str
    thinking: str = "default"
    fallback_used: bool = False
    search_enabled: bool = False
    search_requested: bool = False
    search_used: bool = False


@dataclass(frozen=True, slots=True)
class AIReply:
    text: str
    is_available: bool
    status: Literal["success", "output_blocked", "provider_unavailable", "api_error", "timeout", "model_unavailable", "configuration_error", "search_error", "search_unavailable", "attribution_unavailable", "question_too_long"] = "success"
    moderation_source: Literal["editable_filter", "filter_timeout", "protected_policy"] | None = None
    matched_category: str | None = None
    matched_rule: str | None = None
    generation: AIGenerationDetails | None = field(default=None, compare=False)


class AIService(Protocol):
    @property
    def is_available(self) -> bool: ...

    async def generate_reply(
        self,
        prompt: str,
        user_id: str,
        memory_context: str | None = None,
        stream_category: str | None = None,
    ) -> AIReply: ...


@dataclass(frozen=True, slots=True)
class AIMemoryExchange:
    request_text: str
    response_text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WeatherReport:
    city: str
    temperature_celsius: float
    condition: str
    wind_speed_kmh: float


class WeatherService(Protocol):
    async def get_current_weather(self, city: str) -> WeatherReport | None: ...
