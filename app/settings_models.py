"""Shared settings constraints; storage and recovery remain owned by each store."""

from typing import Annotated, Literal

from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field,
                      StrictFloat, StrictInt, StrictStr, TypeAdapter,
                      ValidationError)
from pydantic_core import PydanticCustomError

from app.errors import validation_error
from app.utils.text import normalize_command_name


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


def parse(model, value, **kwargs):
    try:
        return model.model_validate(value, **kwargs)
    except ValidationError as error:
        raise validation_error(error) from None


def field_value(annotation, value, field):
    try:
        return TypeAdapter(annotation).validate_python(value)
    except ValidationError as error:
        raise validation_error(error, field=field) from None


def _command(value):
    return normalize_command_name(value) if isinstance(value, str) else value


def single_line(value):
    if not value.strip() or "\n" in value or "\r" in value:
        raise PydanticCustomError("text", "Invalid single-line text")
    return value.strip()


def utf8(value):
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise PydanticCustomError("text", "Invalid Unicode") from None
    return value


def byte_limit(maximum):
    def check(value):
        utf8(value)
        if len(value.encode("utf-8")) > maximum:
            raise PydanticCustomError("bytes_too_long", "Text exceeds byte limit", {"max_length": maximum})
        return value
    return AfterValidator(check)


CommandName = Annotated[StrictStr, BeforeValidator(_command), Field(min_length=1, max_length=40, pattern=r"^[^\s!{}]+$")]
SingleLine = Annotated[StrictStr, AfterValidator(single_line)]
ChatLine = Annotated[StrictStr, byte_limit(450), AfterValidator(single_line)]
ControlFree = Annotated[StrictStr, Field(pattern=r"^[^\x00-\x1f\x7f]*$"), AfterValidator(utf8)]
CooldownSeconds = Annotated[StrictFloat, Field(ge=0, le=86400, allow_inf_nan=False)]
NonNegativeSeconds = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
BurstInterval = Annotated[StrictInt, Field(ge=0, le=1000)]
EntryLimit = Annotated[StrictInt, Field(ge=1, le=10)]
CreationOrder = Annotated[StrictInt, Field(ge=0, lt=2**53)]
StreamAvailability = Literal["anytime", "live_only", "offline_only"]
SendAs = Literal["chat", "mention", "reply"]
PermissionName = Literal["USER", "SUBSCRIBER", "VIP", "MODERATOR", "BROADCASTER"]
Identifier = Annotated[StrictStr, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]
UserId = Annotated[StrictStr, Field(min_length=1, max_length=20, pattern=r"^[0-9]+$")]
InterfaceLanguage = Literal["en", "uk", "ru"]
OperationMode = Literal["always_on", "stream_only", "manual", "disabled"]
