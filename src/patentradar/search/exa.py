"""Exa Search API provider."""

from __future__ import annotations

import os

import httpx

from patentradar.schemas import SearchResult

from .base import SearchProvider, build_result_id
from .filters import static_excluded_domains
from .result_normalizer import canonical_url, compact_snippet


class ExaProvider(SearchProvider):
    """Exa neural-search provider.

    Exa's neural embedding does NOT honor `-keyword` minus operators in the
    query string (would actually boost the negated term). Use the API's
    native `excludeDomains` array for blacklisting instead.
    """

    name = "exa"
    endpoint = "https://api.exa.ai/search"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        extra_exclude_domains: list[str] | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("EXA_API_KEY", "")
        self.timeout = timeout
        self._extra_exclude_domains = extra_exclude_domains or []

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, *, query_id: str, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            return []
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        exclude_domains = sorted({*static_excluded_domains(), *self._extra_exclude_domains})
        body = {
            "query": query,
            "numResults": max_results,
            "type": "auto",
            "contents": {"text": {"maxCharacters": 800}},
            "excludeDomains": exclude_domains,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.endpoint, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        results: list[SearchResult] = []
        for rank, item in enumerate(data.get("results", [])[:max_results], start=1):
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
                    snippet=compact_snippet(str(item.get("text") or item.get("summary") or "")),
                    published_date=str(item.get("publishedDate") or ""),
                    rank=rank,
                )
            )
        return results
