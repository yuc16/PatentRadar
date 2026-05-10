"""Brave Search API provider."""

from __future__ import annotations

import os

import httpx

from patentradar.schemas import SearchResult

from .base import SearchProvider, build_result_id
from .result_normalizer import canonical_url, compact_snippet


class BraveProvider(SearchProvider):
    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.getenv("BRAVE_API_KEY", "")
        self.timeout = timeout

    def search(self, *, query_id: str, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            return []
        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
        }
        params = {
            "q": query,
            "count": max_results,
            "country": "CN",
            "search_lang": "zh-hans",
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(self.endpoint, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
        web_results = (data.get("web") or {}).get("results") or []
        results: list[SearchResult] = []
        for rank, item in enumerate(web_results[:max_results], start=1):
            url = canonical_url(str(item.get("url") or ""))
            if not url:
                continue
            results.append(
                SearchResult(
                    result_id=build_result_id(self.name, query_id, rank),
                    query_id=query_id,
                    query=query,
                    provider=self.name,
                    title=str(item.get("title") or ""),
                    url=url,
                    snippet=compact_snippet(str(item.get("description") or "")),
                    published_date=str(item.get("age") or ""),
                    rank=rank,
                )
            )
        return results
