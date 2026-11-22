"""User-facing failures carry their catalog identity from the source."""

from app.ui_messages import MESSAGES


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


def error_result(error: BaseException | str, *, fallback: str = "webview_host.management_operation_unavailable_check_profile_storage") -> dict:
    """Serialize a known diagnostic; unexpected exceptions never expose their text."""
    if isinstance(error, UserError):
        return {"ok": False, "error_code": error.code, "error_params": error.params}
    return {"ok": False, "error_code": error if isinstance(error, str) else fallback, "error_params": {}}
