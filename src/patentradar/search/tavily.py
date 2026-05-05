"""Tavily (https://tavily.com/) search / extract / crawl.

PRD 角色：search 通用补充；extract 抽 PDF/长文；crawl 站点深挖。
"""

from __future__ import annotations

import asyncio
import os

import httpx

from ..config import SEARCH_KEYS
from .base import ExtractedPage, SearchError, SearchHit

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
CRAWL_URL = "https://api.tavily.com/crawl"
DEFAULT_TIMEOUT = 60
EXTRACT_TIMEOUT = 60
CRAWL_TIMEOUT = 90


def _key() -> str:
    key = SEARCH_KEYS.get("tavily")
    if not key:
        raise SearchError("tavily", "TAVILY_API_KEY 未配置")
    return key


def _headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/json",
    }
    project_id = os.getenv("TAVILY_PROJECT", "").strip()
    if project_id:
        headers["X-Project-ID"] = project_id
    return headers


async def _post_json_async(
    url: str,
    body: dict,
    *,
    timeout_s: int,
) -> dict:
    timeout = httpx.Timeout(
        connect=min(15.0, float(timeout_s)),
        read=min(30.0, float(timeout_s)),
        write=15.0,
        pool=15.0,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await asyncio.wait_for(
            client.post(url, headers=_headers(), json=body),
            timeout=float(timeout_s),
        )
        response.raise_for_status()
        return response.json()


def _post_json(url: str, body: dict, *, timeout_s: int) -> dict:
    try:
        return asyncio.run(_post_json_async(url, body, timeout_s=timeout_s))
    except TimeoutError as exc:
        raise SearchError("tavily", f"total timeout after {timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise SearchError("tavily", str(exc)) from exc


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
        "query": query,
        "search_depth": depth,
        "max_results": max(1, min(num, 20)),
        "include_raw_content": include_raw_content,
    }
    if include_domains:
        body["include_domains"] = include_domains
    if exclude_domains:
        body["exclude_domains"] = exclude_domains
    data = _post_json(SEARCH_URL, body, timeout_s=DEFAULT_TIMEOUT)

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
        "urls": urls,
        "extract_depth": "advanced",
    }
    data = _post_json(EXTRACT_URL, body, timeout_s=EXTRACT_TIMEOUT)

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
        "url": url,
        "max_depth": max_depth,
        "limit": limit,
    }
    data = _post_json(CRAWL_URL, body, timeout_s=CRAWL_TIMEOUT)
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
