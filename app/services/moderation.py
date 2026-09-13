"""Baseline moderation policy."""

from app.services.contracts import ModerationDecision


class AllowAllModerationService:
    async def review(self, text: str, user_id: str) -> ModerationDecision:
        return ModerationDecision(allowed=True)