"""Brave Search API (https://api.search.brave.com/).

PRD 角色：广域 Web / 通用网页 / 英文网页补充。
"""

from __future__ import annotations

import httpx

from ..config import SEARCH_KEYS
from .base import SearchError, SearchHit

API_URL = "https://api.search.brave.com/res/v1/web/search"
NEWS_API_URL = "https://api.search.brave.com/res/v1/news/search"
DEFAULT_TIMEOUT = 30


def search(query: str, *, num: int = 10, country: str = "ALL", lang: str | None = None) -> list[SearchHit]:
    key = SEARCH_KEYS.get("brave")
    if not key:
        raise SearchError("brave", "BRAVE_API_KEY 未配置")

    params = {
        "q": query,
        "count": max(1, min(num, 20)),
        "country": country,
        "safesearch": "off",
    }
    if lang:
        params["search_lang"] = lang
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": key,
    }
    try:
        r = httpx.get(API_URL, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("brave", str(exc)) from exc

    hits: list[SearchHit] = []
    web = data.get("web") or {}
    for item in web.get("results", []) or []:
        hits.append(
            SearchHit(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("description", ""),
                source="brave",
                raw=item,
                published_date=item.get("age"),
            )
        )
    return hits


def news_search(
    query: str,
    *,
    num: int = 10,
    country: str = "ALL",
    lang: str | None = None,
    freshness: str | None = None,
) -> list[SearchHit]:
    """Brave News Search, used only for launch/release/mass-production date evidence."""
    key = SEARCH_KEYS.get("brave")
    if not key:
        raise SearchError("brave_news", "BRAVE_API_KEY 未配置")

    params = {
        "q": query,
        "count": max(1, min(num, 20)),
        "country": country,
        "safesearch": "off",
    }
    if lang:
        params["search_lang"] = lang
    if freshness:
        params["freshness"] = freshness
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": key,
    }
    try:
        r = httpx.get(NEWS_API_URL, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("brave_news", str(exc)) from exc

    hits: list[SearchHit] = []
    for item in data.get("results", []) or []:
        snippet_parts = [
            item.get("description", ""),
            *(item.get("extra_snippets") or []),
        ]
        hits.append(
            SearchHit(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet="\n".join(str(s) for s in snippet_parts if str(s).strip()),
                source="brave_news",
                raw=item,
                published_date=item.get("age") or item.get("page_age") or item.get("date"),
            )
        )
    return hits
