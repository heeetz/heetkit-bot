"""User-facing failures carry their catalog identity from the source."""

from app.ui_messages import MESSAGES
from pydantic import ValidationError


class UserError(ValueError):
    def __init__(self, code: str, /, **params: str) -> None:
        # Fail at the source for an invalid code or incomplete template.
        message = MESSAGES[code].format(**params)
        self.code: str = code
        self.params: dict[str, str] = {key: str(value) for key, value in params.items()}
        super().__init__(message)


class UserOSError(UserError, OSError):
    """A coded storage failure that retains the legacy OSError contract."""


class UserRuntimeError(UserError, RuntimeError):
    """A coded lifecycle failure that retains the legacy RuntimeError contract."""


class UserTimeoutError(UserError, TimeoutError):
    """A coded timeout that retains the legacy TimeoutError contract."""


def validation_error(exc: ValidationError, *, field: str | None = None) -> UserError:
    """Convert structured constraints without exposing rejected values or diagnostics."""
    error = exc.errors(include_input=False, include_url=False)[0]
    location = [str(part) for part in error["loc"] if isinstance(part, str)]
    field = field or (location[-1] if location else "settings")
    kind, context = error["type"], error.get("ctx", {})
    if isinstance(context.get("error"), UserError):
        return context["error"]
    if kind == "missing":
        return UserError("validation.required", field=field)
    if kind == "extra_forbidden":
        return UserError("validation.unknown_field", field=field)
    if kind in {"string_too_long", "too_long", "bytes_too_long"}:
        code = {"bytes_too_long": "validation.bytes", "too_long": "validation.too_many"}.get(kind, "validation.too_long")
        return UserError(code, field=field, max=str(context["max_length"]))
    if kind in {"greater_than_equal", "less_than_equal", "greater_than", "less_than"}:
        bound = next(str(context[key]).removesuffix(".0") for key in ("ge", "le", "gt", "lt") if key in context)
        code = "validation.minimum" if kind.startswith("greater") else "validation.maximum"
        return UserError(code, field=field, limit=bound)
    if kind == "literal_error":
        return UserError("validation.choice", field=field, options=str(context["expected"]))
    if kind.endswith("_type") or kind in {"int_parsing", "float_parsing", "finite_number"}:
        expected = {"bool_type": "boolean", "int_type": "integer", "float_type": "number",
                    "string_type": "text", "list_type": "list", "tuple_type": "list",
                    "int_parsing": "integer", "float_parsing": "number", "finite_number": "number"}.get(kind, "object")
        return UserError("validation.type", field=field, expected=expected)
    if kind in {"string_too_short", "too_short"}:
        return UserError("validation.minimum", field=field, limit=str(context["min_length"]))
    return UserError("validation.text", field=field)


def error_result(error: BaseException | str, *, fallback: str = "webview_host.management_operation_unavailable_check_profile_storage") -> dict:
    """Serialize a known diagnostic; unexpected exceptions never expose their text."""
    if isinstance(error, UserError):
        return {"ok": False, "error_code": error.code, "error_params": error.params}
    return {"ok": False, "error_code": error if isinstance(error, str) else fallback, "error_params": {}}
