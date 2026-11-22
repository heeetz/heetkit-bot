"""Tracked Gemini provider metadata and model-setting validation."""

from __future__ import annotations

from app.errors import UserError
import json
import re
from dataclasses import dataclass
from importlib.resources import files

GEMINI_MODELS_RESOURCE = "gemini_models.json"
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
AI_PROVIDERS = {"gemini": "Google Gemini", "deepseek": "DeepSeek", "openai": "OpenAI"}
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_DEEPSEEK_FALLBACK_MODEL = "deepseek-v4-pro"
DEFAULT_OPENAI_MODEL = "gpt-6-luna"
DEFAULT_OPENAI_FALLBACK_MODEL = "gpt-6.1-sol"


def validate_ai_provider(value: object) -> str:
    if not isinstance(value, str) or value not in AI_PROVIDERS:
        raise UserError("ai_models.unknown_ai_provider")
    return value


def validate_provider_models(provider: object, selected: object, fallback: object) -> tuple[str, str]:
    provider = validate_ai_provider(provider)
    selected = validate_provider_model_id(provider, selected)
    fallback = validate_provider_model_id(provider, fallback)
    if selected == fallback:
        raise UserError("ai_models.primary_fallback_models_different")
    return selected, fallback


def validate_provider_model_id(provider: str, value: object) -> str:
    model = validate_gemini_model_id(value, "AI model")
    if provider == "deepseek" and not re.fullmatch(r"deepseek-[A-Za-z0-9._-]+", model):
        raise UserError("ai_models.choose_deepseek_model_deepseek")
    if provider == "gemini" and model.lower().startswith("deepseek-"):
        raise UserError("ai_models.choose_gemini_model_gemini")
    if provider == "openai" and model.lower().startswith(("gemini-", "deepseek-")):
        raise UserError("ai_models.choose_openai_model_openai")
    return model


@dataclass(frozen=True, slots=True)
class GeminiModelPreset:
    id: str
    label: str
    description: str

    def serialize(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
        }


def validate_gemini_model_id(value: object, field_name: str = "Gemini model") -> str:
    if not isinstance(value, str) or not value.strip():
        raise UserError("ai_models.not_empty", field=str(field_name))
    parsed = value.strip()
    if _MODEL_ID_PATTERN.fullmatch(parsed) is None:
        raise UserError("ai_models.contains_unsupported_characters", field=str(field_name))
    return parsed


def _load_gemini_model_config() -> tuple[str, tuple[GeminiModelPreset, ...], str]:
    resource = files("app.resources").joinpath(GEMINI_MODELS_RESOURCE)
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not load built-in Gemini model presets.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Gemini model presets must be a JSON object.")
    provider = payload.get("provider")
    raw_presets = payload.get("presets")
    fallback = payload.get("default_fallback_model")
    if not isinstance(provider, str) or not provider.strip():
        raise RuntimeError("Gemini provider name must be text.")
    if not isinstance(raw_presets, list) or not raw_presets:
        raise RuntimeError("Gemini model presets must be a non-empty list.")
    presets: list[GeminiModelPreset] = []
    for item in raw_presets:
        if not isinstance(item, dict):
            raise RuntimeError("Each Gemini model preset must be an object.")
        model_id = validate_gemini_model_id(item.get("id"), "Gemini preset ID")
        label = item.get("label")
        description = item.get("description")
        if not isinstance(label, str) or not isinstance(description, str):
            raise RuntimeError("Gemini preset labels and descriptions must be text.")
        presets.append(GeminiModelPreset(model_id, label, description))
    fallback_model = validate_gemini_model_id(
        fallback,
        "Default fallback Gemini model",
    )
    if fallback_model not in {preset.id for preset in presets}:
        raise RuntimeError("Default fallback Gemini model must be a shipped preset.")
    return provider.strip(), tuple(presets), fallback_model


GEMINI_PROVIDER_NAME, GEMINI_MODEL_PRESETS, DEFAULT_GEMINI_FALLBACK_MODEL = (
    _load_gemini_model_config()
)
