"""Bocha AI web search provider."""

from __future__ import annotations

import os

import httpx

from patentradar.schemas import SearchResult

from .base import SearchProvider, build_result_id
from .result_normalizer import canonical_url, compact_snippet


class BochaProvider(SearchProvider):
    name = "bocha"
    endpoint = "https://api.bochaai.com/v1/web-search"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.getenv("BOCHA_API_KEY", "")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, *, query_id: str, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            return []
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "query": query,
            "count": max_results,
            "summary": True,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.endpoint, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        web_pages = ((data.get("data") or {}).get("webPages") or {}).get("value") or []
        results: list[SearchResult] = []
        for rank, item in enumerate(web_pages[:max_results], start=1):
            url = canonical_url(str(item.get("url") or ""))
            if not url:
                continue
            results.append(
                SearchResult(
                    result_id=build_result_id(self.name, query_id, rank),
                    query_id=query_id,
                    query=query,
                    provider=self.name,
                    title=str(item.get("name") or item.get("title") or ""),
                    url=url,
                    snippet=compact_snippet(str(item.get("summary") or item.get("snippet") or "")),
                    published_date=str(item.get("datePublished") or ""),
                    rank=rank,
                )
            )
        return results
