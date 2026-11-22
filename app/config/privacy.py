"""Application-owned retention limits, independent of AI memory enablement."""

from app.errors import UserError

AI_HISTORY_RETENTION_DAYS = 60
USER_RETENTION_DAYS = 60
RETENTION_CHECK_SECONDS = 3600
AI_HISTORY_MAX_ENTRIES = 100
AI_CONTEXT_MAX_ENTRIES = 5
PRIVACY_COMMAND = "optout"


def validate_memory_limits(stored: object, context: object) -> tuple[int, int]:
    if type(stored) is not int or not 1 <= stored <= 500:
        raise UserError("privacy.stored_exchanges_integer_1_500")
    if type(context) is not int or not 1 <= context <= min(stored, 50):
        raise UserError("privacy.context_exchanges_1_50")
    return stored, context
