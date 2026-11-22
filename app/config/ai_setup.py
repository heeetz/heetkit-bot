"""Portable, non-secret AI setup. Credentials stay in the host's secure store."""

from dataclasses import asdict, dataclass, field, replace

from app.errors import UserError
from app.config.ai_models import (validate_ai_provider, validate_provider_model_id,
                                  DEFAULT_GEMINI_FALLBACK_MODEL, DEFAULT_DEEPSEEK_MODEL,
                                  DEFAULT_DEEPSEEK_FALLBACK_MODEL, AI_PROVIDERS,
                                  DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_FALLBACK_MODEL)

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
        raise UserError("ai_setup.invalid_ai_setup_fields")

    def selection(raw: object, *, check: bool = True) -> AIModelSelection:
        if not isinstance(raw, dict) or set(raw) != set(AIModelSelection.__dataclass_fields__):
            raise UserError("ai_setup.choose_provider_model_thinking_option_search")
        provider = validate_ai_provider(raw["provider"])
        model = validate_provider_model_id(provider, raw["model"])
        thinking, search = raw["thinking"], raw["search"]
        if not isinstance(thinking, str) or len(thinking) > 32 or type(search) is not bool:
            raise UserError("ai_setup.invalid_thinking_or_search_preference")
        if capabilities and check:
            from app.config.ai_capabilities import validate_model_options
            validate_model_options(provider, model, thinking, search)
        return AIModelSelection(provider, model, thinking, search)

    primary = selection(value.get("primary"))
    fallback = selection(value["fallback"]) if value.get("fallback") is not None else None
    ack = value.get("cross_provider_acknowledged", False)
    if type(ack) is not bool:
        raise UserError("ai_setup.ai_acknowledgement_must_be_boolean")
    if fallback == primary:
        raise UserError("ai_setup.fallback_differ_from_primary_selection")
    if require_consent and fallback and fallback.provider != primary.provider and not ack:
        raise UserError("ai_setup.acknowledge_sending_questions_instructions_permitted_memory")
    lengths = {}
    for name, default, maximum in (("max_question_length", 300, 4000), ("max_answer_length", 220, 450)):
        number = value.get(name, default)
        if type(number) is not int or not 1 <= number <= maximum:
            raise UserError("ai_setup.between_1_characters", field=str(name.replace('_', ' ').capitalize()), maximum=str(maximum))
        lengths[name] = number
    instructions = value.get("shared_instructions")
    if instructions is not None:
        if not isinstance(instructions, str) or len(instructions) > MAX_SHARED_INSTRUCTIONS:
            raise UserError("ai_setup.shared_instructions_must_be_text_of_at_most_20000")
        try:
            instructions.encode("utf-8")
        except UnicodeError:
            raise UserError("ai_setup.shared_instructions_contain_valid_unicode") from None
    drafts = value.get("provider_drafts", {})
    draft_keys = {key for provider in AI_PROVIDERS for key in (provider, f"primary:{provider}", f"fallback:{provider}")}
    if not isinstance(drafts, dict) or set(drafts) - draft_keys:
        raise UserError("ai_setup.invalid_saved_provider_choices")
    parsed_drafts = {}
    for provider, draft in drafts.items():
        saved = selection(draft, check=False)
        if saved.provider != provider.split(":")[-1]:
            raise UserError("ai_setup.saved_provider_choice_belongs_to_another_provider")
        parsed_drafts[provider] = asdict(saved)
    return AISetup(primary, fallback, ack, **lengths, shared_instructions=instructions,
                   provider_drafts=parsed_drafts)


def effective_ai_setup(settings) -> AISetup:
    saved = getattr(settings, "ai_setup", None)
    if saved is not None:
        return saved
    provider = getattr(settings, "ai_provider", "gemini")
    thinking = "off" if provider == "deepseek" else "default"
    default_models = {"gemini": ("gemini-3.5-flash-lite", DEFAULT_GEMINI_FALLBACK_MODEL),
                      "deepseek": (DEFAULT_DEEPSEEK_MODEL, DEFAULT_DEEPSEEK_FALLBACK_MODEL),
                      "openai": (DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_FALLBACK_MODEL)}
    primary = AIModelSelection(provider, getattr(settings, provider + "_model",
        default_models[provider][0]), thinking)
    fallback = AIModelSelection(provider, getattr(settings, provider + "_fallback_model",
        default_models[provider][1]), thinking)
    if provider == "gemini":
        from app.config.ai_capabilities import model_capabilities
        primary = replace(primary, search=model_capabilities(provider, primary.model)["search_supported"])
        fallback = replace(fallback, search=model_capabilities(provider, fallback.model)["search_supported"])
    return AISetup(primary, fallback if fallback != primary else None,
                   max_question_length=getattr(settings, "command_max_arguments_length", 300))
