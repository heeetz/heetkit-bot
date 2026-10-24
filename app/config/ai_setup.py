"""Portable, non-secret AI setup. Credentials stay in the host's secure store."""

from dataclasses import asdict, dataclass, field, replace

from app.config.ai_models import (validate_ai_provider, validate_provider_model_id,
                                  DEFAULT_GEMINI_FALLBACK_MODEL, DEFAULT_DEEPSEEK_MODEL,
                                  DEFAULT_DEEPSEEK_FALLBACK_MODEL)

MAX_SHARED_INSTRUCTIONS = 20000


@dataclass(frozen=True, slots=True)
class AIModelSelection:
    provider: str
    model: str
    thinking: str = "default"
    search: bool = False


@dataclass(frozen=True, slots=True)
class AISetup:
    primary: AIModelSelection
    fallback: AIModelSelection | None = None
    cross_provider_acknowledged: bool = False
    max_question_length: int = 300
    max_answer_length: int = 220
    # None follows shipped defaults; an empty string deliberately removes them.
    shared_instructions: str | None = None
    provider_drafts: dict[str, dict] = field(default_factory=dict)


def parse_ai_setup(value: object, *, capabilities: bool = True, require_consent: bool = True) -> AISetup:
    if not isinstance(value, dict) or set(value) - set(AISetup.__dataclass_fields__):
        raise ValueError("Invalid AI setup fields.")

    def selection(raw: object, *, check: bool = True) -> AIModelSelection:
        if not isinstance(raw, dict) or set(raw) != set(AIModelSelection.__dataclass_fields__):
            raise ValueError("Choose a provider, model, thinking option and search preference.")
        provider = validate_ai_provider(raw["provider"])
        model = validate_provider_model_id(provider, raw["model"])
        thinking, search = raw["thinking"], raw["search"]
        if not isinstance(thinking, str) or len(thinking) > 32 or type(search) is not bool:
            raise ValueError("Invalid thinking or search preference.")
        if capabilities and check:
            from app.config.ai_capabilities import validate_model_options
            validate_model_options(provider, model, thinking, search)
        return AIModelSelection(provider, model, thinking, search)

    primary = selection(value.get("primary"))
    fallback = selection(value["fallback"]) if value.get("fallback") is not None else None
    ack = value.get("cross_provider_acknowledged", False)
    if type(ack) is not bool:
        raise ValueError("AI acknowledgement must be boolean.")
    if fallback == primary:
        raise ValueError("Fallback must differ from the primary selection.")
    if require_consent and fallback and fallback.provider != primary.provider and not ack:
        raise ValueError("Acknowledge sending questions, instructions and permitted memory to the fallback provider.")
    lengths = {}
    for name, default, maximum in (("max_question_length", 300, 4000), ("max_answer_length", 220, 450)):
        number = value.get(name, default)
        if type(number) is not int or not 1 <= number <= maximum:
            raise ValueError(f"{name.replace('_', ' ').capitalize()} must be between 1 and {maximum} characters.")
        lengths[name] = number
    instructions = value.get("shared_instructions")
    if instructions is not None:
        if not isinstance(instructions, str) or len(instructions) > MAX_SHARED_INSTRUCTIONS:
            raise ValueError("Shared instructions must be text of at most 20000 characters.")
        try:
            instructions.encode("utf-8")
        except UnicodeError:
            raise ValueError("Shared instructions must contain valid Unicode.") from None
    drafts = value.get("provider_drafts", {})
    draft_keys = {"gemini", "deepseek", "primary:gemini", "primary:deepseek", "fallback:gemini", "fallback:deepseek"}
    if not isinstance(drafts, dict) or set(drafts) - draft_keys:
        raise ValueError("Invalid saved provider choices.")
    parsed_drafts = {}
    for provider, draft in drafts.items():
        saved = selection(draft, check=False)
        if saved.provider != provider.split(":")[-1]:
            raise ValueError("Saved provider choice belongs to another provider.")
        parsed_drafts[provider] = asdict(saved)
    return AISetup(primary, fallback, ack, **lengths, shared_instructions=instructions,
                   provider_drafts=parsed_drafts)


def effective_ai_setup(settings) -> AISetup:
    saved = getattr(settings, "ai_setup", None)
    if saved is not None:
        return saved
    provider = getattr(settings, "ai_provider", "gemini")
    thinking = "off" if provider == "deepseek" else "default"
    primary = AIModelSelection(provider, getattr(settings, provider + "_model",
        DEFAULT_DEEPSEEK_MODEL if provider == "deepseek" else "gemini-3.5-flash-lite"), thinking)
    fallback = AIModelSelection(provider, getattr(settings, provider + "_fallback_model",
        DEFAULT_DEEPSEEK_FALLBACK_MODEL if provider == "deepseek" else DEFAULT_GEMINI_FALLBACK_MODEL), thinking)
    if provider == "gemini":
        from app.config.ai_capabilities import model_capabilities
        primary = replace(primary, search=model_capabilities(provider, primary.model)["search_supported"])
        fallback = replace(fallback, search=model_capabilities(provider, fallback.model)["search_supported"])
    return AISetup(primary, fallback if fallback != primary else None,
                   max_question_length=getattr(settings, "command_max_arguments_length", 300))
