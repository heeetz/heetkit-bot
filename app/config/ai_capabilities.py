"""Documented, exact model mappings for the APIs implemented by the adapters.

Discovery only establishes model names, never capabilities. Unknown IDs retain
provider-default generation without search. Review these mappings when API/model
versions change; never infer support from a name prefix.

References (verified 2026-10-24):
https://api-docs.deepseek.com/guides/thinking_mode/
https://api-docs.deepseek.com/guides/search/
https://ai.google.dev/gemini-api/docs/generate-content/thinking
https://ai.google.dev/gemini-api/docs/generate-content/google-search
OpenAI mappings verified 2026-10-26:
https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/models/gpt-6.1-sol
https://developers.openai.com/api/docs/guides/tools-web-search
"""

from typing import Any

from app.config.ai_models import validate_ai_provider, validate_provider_model_id

_DEEPSEEK_MODELS = frozenset({
    "deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
})
_GEMINI_LEVELS = {
    "gemini-4-argon": ("low", "medium", "high"),
    "gemini-3.8-flash": ("low", "medium", "high"),
    "gemini-3.6-flash": ("minimal", "low", "medium", "high"),
    "gemini-3.5-flash": ("minimal", "low", "medium", "high"),
    "gemini-3.5-flash-lite": ("minimal", "low", "medium", "high"),
    "gemini-3.1-flash-lite": ("minimal", "low", "medium", "high"),
    "gemini-3.1-flash-lite-preview": ("minimal", "low", "medium", "high"),
    "gemini-3.1-pro-preview": ("low", "medium", "high"),
    "gemini-3-flash-preview": ("minimal", "low", "medium", "high"),
    "gemini-3-pro-preview": ("low", "high"),
}
_GEMINI_BUDGETS = {
    "gemini-2.5-pro": (128, 32768, False),
    "gemini-2.5-flash": (0, 24576, True),
    "gemini-2.5-flash-lite": (512, 24576, True),
}
_GEMINI_SEARCH = frozenset(_GEMINI_LEVELS) | frozenset(_GEMINI_BUDGETS) | {"gemini-2.0-flash"}
_DEFAULT = {"value": "default", "label": "Provider default"}
_OPENAI_LEVELS = {
    "gpt-6-luna": ("none", "low", "medium", "high", "xhigh", "max"),
    "gpt-6.1-sol": ("low", "medium", "high", "xhigh", "max"),
}
KNOWN_MODELS = {
    "deepseek": tuple(sorted(_DEEPSEEK_MODELS)),
    "gemini": tuple(sorted(_GEMINI_SEARCH | frozenset(_GEMINI_LEVELS))),
    "openai": tuple(_OPENAI_LEVELS),
}


def model_capabilities(provider: str, model: str) -> dict[str, Any]:
    provider = validate_ai_provider(provider)
    model = validate_provider_model_id(provider, model)
    options = [dict(_DEFAULT)]
    known = False
    search = False
    reason = "This model's search and thinking controls have not been verified for this API."
    if provider == "deepseek" and model in _DEEPSEEK_MODELS:
        known = search = True
        options += [{"value": value, "label": value.capitalize()} for value in ("off", "low", "high", "max")]
        reason = "Search and Fetch use DeepSeek's API and this provider's key; calls are bounded."
    elif provider == "openai" and model in _OPENAI_LEVELS:
        known = search = True
        options += [{"value": value, "label": value.capitalize()} for value in _OPENAI_LEVELS[model]]
        reason = ("OpenAI Web Search uses this key, at most two tool calls and low search context. "
                  "Search adds charges; cited URLs must fit the answer limit or the answer is withheld.")
    elif provider == "gemini":
        known = model in _GEMINI_LEVELS or model in _GEMINI_BUDGETS or model in _GEMINI_SEARCH
        search = model in _GEMINI_SEARCH
        if model in _GEMINI_LEVELS:
            options += [{"value": value, "label": value.capitalize()} for value in _GEMINI_LEVELS[model]]
        elif model in _GEMINI_BUDGETS:
            minimum, maximum, off = _GEMINI_BUDGETS[model]
            if off:
                options.append({"value": "off", "label": "Off"})
            if minimum:
                options.append({"value": f"budget:{minimum}", "label": f"Minimum ({minimum} thinking tokens)"})
            options.append({"value": f"budget:{maximum}", "label": f"Maximum ({maximum} thinking tokens)"})
        if search:
            reason = ("Google Search requires Search Suggestions and source attribution. "
                      "Twitch chat cannot render the required Suggestions; grounded answers cannot be sent there.")
    return {
        "provider": provider, "model": model, "known": known,
        "thinking_options": options, "search_supported": search,
        "search_reason": reason, "attribution_required": provider == "gemini" and search,
        "api_version": {"deepseek": "chat-completions", "gemini": "v1beta/generateContent",
                        "openai": "v1/responses"}[provider],
    }


def validate_model_options(provider: str, model: str, thinking: str, search: bool) -> None:
    capabilities = model_capabilities(provider, model)
    if thinking not in {option["value"] for option in capabilities["thinking_options"]}:
        raise ValueError("Thinking choice is unavailable for this model. Choose a supported option explicitly.")
    if type(search) is not bool:
        raise ValueError("Internet search must be on or off.")
    if search and not capabilities["search_supported"]:
        raise ValueError(capabilities["search_reason"])


def native_thinking_parameters(provider: str, model: str, thinking: str) -> dict[str, Any]:
    """Return only native fields supported by this exact documented mapping."""
    validate_model_options(provider, model, thinking, False)
    if thinking == "default":
        return {}
    if provider == "openai":
        return {"reasoning": {"effort": thinking}}
    if provider == "deepseek":
        if thinking == "off":
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "enabled"}, "reasoning_effort": thinking}
    if thinking == "off":
        return {"thinking_budget": 0, "include_thoughts": False}
    if thinking.startswith("budget:"):
        return {"thinking_budget": int(thinking.split(":", 1)[1]), "include_thoughts": False}
    return {"thinking_level": thinking, "include_thoughts": False}
