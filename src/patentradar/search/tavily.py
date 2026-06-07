"""Tavily Search API provider with multi-key rotation."""

from __future__ import annotations

import logging
import os
import threading

import httpx

from patentradar.schemas import SearchResult

from .base import SearchProvider, build_result_id
from .result_normalizer import canonical_url, compact_snippet

logger = logging.getLogger(__name__)

_QUOTA_KEYWORDS = (
    "quota", "rate limit", "usage limit", "exceeded", "429", "403", "401", "432",
)
# Tavily 用 432（非标 HTTP）表示当前 key 已超月度额度；429 是常规限流；401/403 是无效/失效 key。
_QUOTA_STATUSES = (401, 403, 429, 432)


def _load_tavily_key_pool() -> list[str]:
    """Read Tavily keys from env. Multiple keys let us rotate when one
    key hits its monthly quota.

    Format: comma-separated values in either ``TAVILY_API_KEYS`` (preferred)
    or ``TAVILY_API_KEY`` (backwards-compatible; also accepts a single key).
    """
    raw = os.getenv("TAVILY_API_KEYS") or os.getenv("TAVILY_API_KEY") or ""
    keys = [part.strip() for part in raw.split(",")]
    keys = [k for k in keys if k]
    return list(dict.fromkeys(keys))


class TavilyProvider(SearchProvider):
    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        if api_key:
            self._keys = [api_key]
        else:
            self._keys = _load_tavily_key_pool()
        self._index = 0
        self._lock = threading.Lock()
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._keys)

    def search(self, *, query_id: str, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._keys:
            return []
        body = {
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        last_exc: Exception | None = None
        for _ in range(len(self._keys)):
            key = self._current_key()
            headers = {"Authorization": f"Bearer {key}"}
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(self.endpoint, headers=headers, json=body)
                if response.status_code in _QUOTA_STATUSES:
                    logger.warning(
                        "Tavily key %d/%d quota/auth issue (status=%d), rotating",
                        self._index + 1, len(self._keys), response.status_code,
                    )
                    self._rotate_key()
                    continue
                response.raise_for_status()
                data = response.json()
                return self._parse(query_id=query_id, query=query, data=data, max_results=max_results)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if any(k in str(exc).lower() for k in _QUOTA_KEYWORDS):
                    logger.warning("Tavily key %d/%d quota error: %s, rotating", self._index + 1, len(self._keys), exc)
                    self._rotate_key()
                    continue
                raise
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("Tavily transport error key=%d/%d: %s, rotating", self._index + 1, len(self._keys), exc)
                self._rotate_key()
                continue
        if last_exc:
            logger.error("Tavily exhausted all %d keys: %s", len(self._keys), last_exc)
        return []

    def _current_key(self) -> str:
        with self._lock:
            return self._keys[self._index % len(self._keys)]

    def _rotate_key(self) -> None:
        with self._lock:
            self._index = (self._index + 1) % len(self._keys)

    def _parse(self, *, query_id: str, query: str, data: dict, max_results: int) -> list[SearchResult]:
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
                    snippet=compact_snippet(str(item.get("content") or "")),
                    published_date=str(item.get("published_date") or ""),
                    rank=rank,
                )
            )
        return results
