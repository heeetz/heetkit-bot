"""Portable, non-secret AI setup. Credentials stay in the host's secure store."""

from dataclasses import dataclass, field, replace

from app.errors import UserError
from typing import Annotated
from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationInfo, model_validator
from app.settings_models import SettingsModel, utf8, parse
from pydantic import AfterValidator
from app.config.ai_models import (validate_provider_model_id, validate_ai_provider, provider_type,
                                  DEFAULT_GEMINI_FALLBACK_MODEL, DEFAULT_DEEPSEEK_MODEL,
                                  DEFAULT_DEEPSEEK_FALLBACK_MODEL,
                                  DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_FALLBACK_MODEL, MAX_AI_CONNECTIONS)

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


class AIModelSelectionModel(SettingsModel):
    model_config = ConfigDict(extra="forbid")
    # A provider connection id; its type decides model and capability rules.
    provider: Annotated[StrictStr, AfterValidator(validate_ai_provider)]
    model: StrictStr
    thinking: Annotated[StrictStr, Field(max_length=32)]
    search: StrictBool

    @model_validator(mode="after")
    def model_id(self):
        self.model = validate_provider_model_id(self.provider, self.model)
        return self


class AISetupModel(SettingsModel):
    model_config = ConfigDict(extra="forbid")
    primary: AIModelSelectionModel
    fallback: AIModelSelectionModel | None = None
    cross_provider_acknowledged: StrictBool = False
    max_question_length: Annotated[StrictInt, Field(ge=1, le=4000)] = 300
    max_answer_length: Annotated[StrictInt, Field(ge=1, le=450)] = 220
    shared_instructions: Annotated[StrictStr, Field(max_length=MAX_SHARED_INSTRUCTIONS), AfterValidator(utf8)] | None = None
    # Remembered choices per connection, optionally per slot ("fallback:deepseek-a1b2c3").
    provider_drafts: Annotated[dict[Annotated[StrictStr, Field(pattern=r"^(?:(?:primary|fallback):)?(?:gemini|deepseek|openai|custom)(?:-[a-z0-9]{6})?$")],
                                    AIModelSelectionModel], Field(max_length=2 * 3 * MAX_AI_CONNECTIONS)] = {}

    @model_validator(mode="after")
    def selections(self, info: ValidationInfo):
        context = info.context or {}
        if self.fallback == self.primary:
            raise UserError("ai_setup.fallback_differ_from_primary_selection")
        # v1: a hosted model never hands prompts and memory to a custom endpoint.
        if self.fallback and provider_type(self.fallback.provider) == "custom":
            raise UserError("ai_setup.custom_primary_only")
        # Consent covers another company; another key of the same provider needs none.
        if (context.get("require_consent", True) and self.fallback
                and provider_type(self.fallback.provider) != provider_type(self.primary.provider)
                and not self.cross_provider_acknowledged):
            raise UserError("ai_setup.acknowledge_sending_questions_instructions_permitted_memory")
        if context.get("capabilities", True):
            from app.config.ai_capabilities import validate_model_options
            for item in (self.primary, self.fallback):
                if item:
                    validate_model_options(item.provider, item.model, item.thinking, item.search)
        for key, draft in self.provider_drafts.items():
            if draft.provider != key.split(":")[-1] or (key.startswith("fallback:") and provider_type(draft.provider) == "custom"):
                raise UserError("ai_setup.saved_provider_choice_belongs_to_another_provider")
        return self


def parse_ai_setup(value: object, *, capabilities: bool = True, require_consent: bool = True) -> AISetup:
    item = parse(AISetupModel, value, context=dict(capabilities=capabilities, require_consent=require_consent))
    return AISetup(primary=AIModelSelection(**item.primary.model_dump()),
        fallback=AIModelSelection(**item.fallback.model_dump()) if item.fallback else None,
        **item.model_dump(exclude={"primary", "fallback"}))


def effective_ai_setup(settings) -> AISetup:
    saved = getattr(settings, "ai_setup", None)
    if saved is not None:
        return saved
    provider = getattr(settings, "ai_provider", "gemini")
    if provider == "custom":  # Custom exists only with a saved setup.
        provider = "gemini"
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
