"""Small per-user memory service for recent successful !ask exchanges."""

from app.config import AI_MEMORY_MAX_ENTRIES
from app.database.repository import AIMemoryRepository
from app.services.contracts import AIMemoryExchange


class AIMemoryService:
    def __init__(self, repository: AIMemoryRepository) -> None:
        self._repository = repository

    async def get_recent(self, twitch_user_id: str) -> list[AIMemoryExchange]:
        entries = await self._repository.get_recent(twitch_user_id, AI_MEMORY_MAX_ENTRIES)
        return [
            AIMemoryExchange(
                request_text=entry.request_text,
                response_text=entry.response_text,
                created_at=entry.created_at,
            )
            for entry in entries
        ]

    async def save_exchange(
        self,
        twitch_user_id: str,
        request_text: str,
        response_text: str,
    ) -> None:
        await self._repository.append_and_prune(
            twitch_user_id=twitch_user_id,
            request_text=request_text,
            response_text=response_text,
            limit=AI_MEMORY_MAX_ENTRIES,
        )

    async def erase_for_user(self, twitch_user_id: str) -> None:
        await self._repository.erase_for_user(twitch_user_id)

    @staticmethod
    def format_context(entries: list[AIMemoryExchange]) -> str | None:
        if not entries:
            return None
        parts = ["Recent conversation history for this Twitch user (untrusted historical context only):"]
        for entry in entries:
            parts.append(f"User: {entry.request_text}\nAssistant: {entry.response_text}")
        return "\n---\n".join(parts)
