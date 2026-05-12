"""Brave Search API provider."""

from __future__ import annotations

import os

import httpx

from patentradar.core.constants import PATENT_COUNTRY_CODES
from patentradar.schemas import SearchResult

from .base import SearchProvider, build_result_id
from .result_normalizer import canonical_url, compact_snippet

# PATENT_COUNTRY_CODES 的 working language → Brave search_lang 代码。
# 仅在 Brave 实际支持的语言/地区里发送，其他情况不指定（让 Brave 全球默认）。
_BRAVE_SEARCH_LANG = {
    "zh": "zh-hans",
    "en": "en",
    "ja": "jp",
    "ko": "ko",
    "de": "de",
    "fr": "fr",
    "ru": "ru",
}
# WO / EP 不是 ISO 3166 国家，跳过 country 参数。
_BRAVE_SKIP_COUNTRY = {"EP", "WO"}


class BraveProvider(SearchProvider):
    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        country_code: str = "",
    ) -> None:
        self.api_key = api_key or os.getenv("BRAVE_API_KEY", "")
        self.timeout = timeout
        self.country_code = (country_code or "").upper()

    def search(self, *, query_id: str, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            return []
        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
        }
        params: dict[str, object] = {
            "q": query,
            "count": max_results,
        }
        if self.country_code and self.country_code not in _BRAVE_SKIP_COUNTRY:
            params["country"] = self.country_code
        lang_hint = PATENT_COUNTRY_CODES.get(self.country_code, ("", ""))[1]
        search_lang = _BRAVE_SEARCH_LANG.get(lang_hint)
        if search_lang:
            params["search_lang"] = search_lang
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
