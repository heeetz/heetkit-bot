"""Tracked Gemini provider metadata and model-setting validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files

GEMINI_MODELS_RESOURCE = "gemini_models.json"
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


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
        raise ValueError(f"{field_name} must not be empty.")
    parsed = value.strip()
    if _MODEL_ID_PATTERN.fullmatch(parsed) is None:
        raise ValueError(f"{field_name} contains unsupported characters.")
    return parsed


def validate_gemini_model_settings(
    selected_model: object,
    fallback_model: object,
) -> tuple[str, str]:
    selected = validate_gemini_model_id(selected_model, "Selected Gemini model")
    fallback = validate_gemini_model_id(fallback_model, "Fallback Gemini model")
    if selected == fallback:
        raise ValueError("Selected and fallback Gemini models must be different.")
    return selected, fallback


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
