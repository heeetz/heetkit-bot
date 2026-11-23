"""Tracked Gemini provider metadata and model-setting validation."""

from __future__ import annotations

from app.errors import UserError
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from ipaddress import ip_address
from urllib.parse import urlsplit

GEMINI_MODELS_RESOURCE = "gemini_models.json"
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
# Custom is one operator-defined OpenAI-compatible endpoint; Desktop only (task 2).
AI_PROVIDERS = {"gemini": "Google Gemini", "deepseek": "DeepSeek", "openai": "OpenAI",
                "custom": "Custom (OpenAI-compatible)"}
# Local servers such as LM Studio name quantized variants with "@".
_CUSTOM_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$")
MAX_CUSTOM_BASE_URL_LENGTH = 2048
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
    if provider == "custom":
        if not isinstance(value, str) or not value.strip():
            raise UserError("ai_models.not_empty", field="AI model")
        if _CUSTOM_MODEL_ID_PATTERN.fullmatch(value.strip()) is None:
            raise UserError("ai_models.contains_unsupported_characters", field="AI model")
        return value.strip()
    model = validate_gemini_model_id(value, "AI model")
    if provider == "deepseek" and not re.fullmatch(r"deepseek-[A-Za-z0-9._-]+", model):
        raise UserError("ai_models.choose_deepseek_model_deepseek")
    if provider == "gemini" and model.lower().startswith("deepseek-"):
        raise UserError("ai_models.choose_gemini_model_gemini")
    if provider == "openai" and model.lower().startswith(("gemini-", "deepseek-")):
        raise UserError("ai_models.choose_openai_model_openai")
    return model


def _is_loopback(host: str) -> bool:
    if host.lower().removesuffix(".") == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def validate_custom_base_url(value: object) -> str:
    """Accept HTTPS anywhere and HTTP only on this computer; no credentials, query or fragment."""
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_CUSTOM_BASE_URL_LENGTH:
        raise UserError("ai_models.custom_base_url_invalid")
    url = value.strip().rstrip("/")
    try:
        parts = urlsplit(url)
        parts.port  # Raises for an invalid port.
    except ValueError:
        raise UserError("ai_models.custom_base_url_invalid") from None
    scheme = parts.scheme.lower()
    if (scheme not in {"http", "https"} or not parts.hostname or "@" in parts.netloc
            or parts.query or parts.fragment or "?" in url or "#" in url or any(ord(c) <= 32 for c in url)):
        raise UserError("ai_models.custom_base_url_invalid")
    if scheme == "http" and not _is_loopback(parts.hostname):
        raise UserError("ai_models.custom_base_url_http_local_only")
    return url


def custom_base_url_origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or (443 if scheme == "https" else 80)


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
