"""Tavily (https://tavily.com/) search / extract / crawl.

PRD 角色：search 通用补充；extract 抽 PDF/长文；crawl 站点深挖。
"""

from __future__ import annotations

import httpx

from ..config import SEARCH_KEYS
from .base import ExtractedPage, SearchError, SearchHit

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
CRAWL_URL = "https://api.tavily.com/crawl"
DEFAULT_TIMEOUT = 60


def _key() -> str:
    key = SEARCH_KEYS.get("tavily")
    if not key:
        raise SearchError("tavily", "TAVILY_API_KEY 未配置")
    return key


def search(
    query: str,
    *,
    num: int = 10,
    depth: str = "advanced",  # basic | advanced
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    include_raw_content: bool = False,
) -> list[SearchHit]:
    body = {
        "api_key": _key(),
        "query": query,
        "search_depth": depth,
        "max_results": max(1, min(num, 20)),
        "include_raw_content": include_raw_content,
    }
    if include_domains:
        body["include_domains"] = include_domains
    if exclude_domains:
        body["exclude_domains"] = exclude_domains
    try:
        r = httpx.post(SEARCH_URL, json=body, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("tavily", str(exc)) from exc

    hits: list[SearchHit] = []
    for item in data.get("results", []) or []:
        hits.append(
            SearchHit(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("content", ""),
                source="tavily",
                raw=item,
                score=item.get("score"),
                published_date=item.get("published_date"),
            )
        )
    return hits


def extract(urls: list[str]) -> list[ExtractedPage]:
    """正文抽取（PDF / 长文均可）。"""
    if not urls:
        return []
    body = {
        "api_key": _key(),
        "urls": urls,
        "extract_depth": "advanced",
    }
    try:
        r = httpx.post(EXTRACT_URL, json=body, timeout=120)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("tavily", str(exc)) from exc

    out: list[ExtractedPage] = []
    for item in data.get("results", []) or []:
        out.append(
            ExtractedPage(
                url=item.get("url", ""),
                title="",
                text=item.get("raw_content") or item.get("content") or "",
                source="tavily_extract",
                raw=item,
            )
        )
    return out


def crawl(url: str, *, max_depth: int = 1, limit: int = 20) -> list[ExtractedPage]:
    """站点抓取。"""
    body = {
        "api_key": _key(),
        "url": url,
        "max_depth": max_depth,
        "limit": limit,
    }
    try:
        r = httpx.post(CRAWL_URL, json=body, timeout=180)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("tavily", str(exc)) from exc
    out: list[ExtractedPage] = []
    for item in data.get("results", []) or []:
        out.append(
            ExtractedPage(
                url=item.get("url", ""),
                title="",
                text=item.get("raw_content") or item.get("content") or "",
                source="tavily_crawl",
                raw=item,
            )
        )
    return out
