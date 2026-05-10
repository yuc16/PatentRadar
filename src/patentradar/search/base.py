"""Search provider base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod

from patentradar.schemas import SearchProviderName, SearchResult


class SearchProvider(ABC):
    name: SearchProviderName

    @abstractmethod
    def search(self, *, query_id: str, query: str, max_results: int = 5) -> list[SearchResult]:
        """Return normalized search results."""


def build_result_id(provider: str, query_id: str, rank: int) -> str:
    return f"{provider}-{query_id}-{rank:02d}"
