"""Brave Search API (https://api.search.brave.com/).

PRD 角色：广域 Web / 通用网页 / 英文网页补充。
"""

from __future__ import annotations

import httpx

from ..config import SEARCH_KEYS
from .base import SearchError, SearchHit

API_URL = "https://api.search.brave.com/res/v1/web/search"
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
