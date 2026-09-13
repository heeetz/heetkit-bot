"""Web-search service placeholder."""

from app.services.contracts import SearchResult


class DisabledWebSearchService:
    async def search(self, query: str, limit: int = 3) -> list[SearchResult]:
        return []