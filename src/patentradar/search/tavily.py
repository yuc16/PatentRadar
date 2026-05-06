"""Tavily (https://tavily.com/) search / extract / crawl.

PRD 角色：search 通用补充；extract 抽 PDF/长文；crawl 站点深挖。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading

import httpx

from ..config import SEARCH_KEY_RINGS, SEARCH_KEYS
from .base import ExtractedPage, SearchError, SearchHit

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
CRAWL_URL = "https://api.tavily.com/crawl"
DEFAULT_TIMEOUT = 60
EXTRACT_TIMEOUT = 60
CRAWL_TIMEOUT = 90
RETRYABLE_KEY_STATUS = {401, 402, 403, 429}

logger = logging.getLogger(__name__)
_KEY_LOCK = threading.Lock()
_KEY_INDEX = 0


def _keys() -> list[str]:
    keys = SEARCH_KEY_RINGS.get("tavily") or []
    if not keys and SEARCH_KEYS.get("tavily"):
        keys = [SEARCH_KEYS["tavily"]]
    if not keys:
        raise SearchError("tavily", "TAVILY_API_KEY 未配置")
    return keys


def _next_key() -> tuple[str, int, int]:
    global _KEY_INDEX
    keys = _keys()
    with _KEY_LOCK:
        idx = _KEY_INDEX % len(keys)
        _KEY_INDEX += 1
    return keys[idx], idx + 1, len(keys)


def _headers(key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {key}",
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
    key: str,
) -> dict:
    timeout = httpx.Timeout(
        connect=min(15.0, float(timeout_s)),
        read=min(30.0, float(timeout_s)),
        write=15.0,
        pool=15.0,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await asyncio.wait_for(
            client.post(url, headers=_headers(key), json=body),
            timeout=float(timeout_s),
        )
        response.raise_for_status()
        return response.json()


def _post_json(url: str, body: dict, *, timeout_s: int) -> dict:
    n_keys = len(_keys())
    last_exc: Exception | None = None
    for _ in range(n_keys):
        key, key_idx, total = _next_key()
        try:
            return asyncio.run(_post_json_async(
                url,
                body,
                timeout_s=timeout_s,
                key=key,
            ))
        except TimeoutError as exc:
            raise SearchError("tavily", f"total timeout after {timeout_s}s") from exc
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status in RETRYABLE_KEY_STATUS and total > 1:
                logger.info(
                    "tavily key slot %d/%d failed with status=%d, trying next key",
                    key_idx,
                    total,
                    status,
                )
                continue
            raise SearchError("tavily", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise SearchError("tavily", str(exc)) from exc
    raise SearchError("tavily", f"所有 Tavily key 均失败: {last_exc}")


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
