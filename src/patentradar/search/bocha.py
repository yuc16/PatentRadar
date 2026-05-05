"""Bocha AI 搜索 (https://api.bochaai.com/).

PRD 角色：中文 Web / 新闻 / 企业官网 / 行业文章 / 中文产品资料。
"""

from __future__ import annotations

import httpx

from ..config import SEARCH_KEYS
from .base import SearchError, SearchHit

API_URL = "https://api.bochaai.com/v1/web-search"
DEFAULT_TIMEOUT = 30


def search(query: str, *, num: int = 10, freshness: str = "noLimit") -> list[SearchHit]:
    """Bocha Web Search.

    freshness: noLimit | oneDay | oneWeek | oneMonth | oneYear
    """
    key = SEARCH_KEYS.get("bocha")
    if not key:
        raise SearchError("bocha", "BOCHA_API_KEY 未配置")

    body = {
        "query": query,
        "freshness": freshness,
        "summary": True,
        "count": max(1, min(num, 50)),
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        r = httpx.post(API_URL, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("bocha", str(exc)) from exc

    if data.get("code") not in (200, 0, None):
        raise SearchError("bocha", f"API 错误: {data.get('msg') or data}")

    hits: list[SearchHit] = []
    web_pages = (data.get("data") or {}).get("webPages") or {}
    for item in web_pages.get("value", []) or []:
        hits.append(
            SearchHit(
                url=item.get("url", ""),
                title=item.get("name", "") or item.get("title", ""),
                snippet=item.get("summary") or item.get("snippet", ""),
                source="bocha",
                raw=item,
                published_date=item.get("datePublished"),
            )
        )
    return hits
