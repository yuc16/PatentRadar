"""Exa.ai (https://exa.ai/) 语义搜索 + 正文抽取.

PRD 角色：语义相似 / 英文资料 / 技术变体 / 海外候选发现。
"""

from __future__ import annotations

import httpx

from ..config import SEARCH_KEYS
from .base import ExtractedPage, SearchError, SearchHit

SEARCH_URL = "https://api.exa.ai/search"
CONTENTS_URL = "https://api.exa.ai/contents"
DEFAULT_TIMEOUT = 30


def search(
    query: str,
    *,
    num: int = 10,
    type_: str = "neural",  # neural | keyword | auto
    use_autoprompt: bool = True,
    include_text: bool = False,
    include_highlights: bool = True,
    highlights_chars: int = 800,
) -> list[SearchHit]:
    key = SEARCH_KEYS.get("exa")
    if not key:
        raise SearchError("exa", "EXA_API_KEY 未配置")

    body = {
        "query": query,
        "type": type_,
        "useAutoprompt": use_autoprompt,
        "numResults": max(1, min(num, 25)),
    }
    contents: dict = {}
    if include_highlights:
        contents["highlights"] = {
            "query": query,
            "maxCharacters": max(200, min(highlights_chars, 2000)),
        }
    if include_text:
        contents["text"] = {"maxCharacters": max(300, min(highlights_chars, 2000))}
    if contents:
        body["contents"] = contents
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    try:
        r = httpx.post(SEARCH_URL, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("exa", str(exc)) from exc

    hits: list[SearchHit] = []
    for item in data.get("results", []) or []:
        snippet = ""
        highlights = item.get("highlights")
        if isinstance(highlights, list):
            snippet = "\n".join(str(h).strip() for h in highlights if str(h).strip())
        elif isinstance(highlights, str):
            snippet = highlights.strip()
        text = item.get("text")
        if not snippet and text:
            snippet = text[:300]
        if not snippet:
            summary = item.get("summary")
            if isinstance(summary, str):
                snippet = summary[:500]
        hits.append(
            SearchHit(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=snippet,
                source="exa",
                raw=item,
                score=item.get("score"),
                published_date=item.get("publishedDate"),
            )
        )
    return hits


def contents(urls: list[str]) -> list[ExtractedPage]:
    """批量抽取 URL 正文（Exa Contents API）。"""
    if not urls:
        return []
    key = SEARCH_KEYS.get("exa")
    if not key:
        raise SearchError("exa", "EXA_API_KEY 未配置")
    body = {"ids": urls, "text": True}
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    try:
        r = httpx.post(CONTENTS_URL, headers=headers, json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise SearchError("exa", str(exc)) from exc

    out: list[ExtractedPage] = []
    for item in data.get("results", []) or []:
        out.append(
            ExtractedPage(
                url=item.get("url", ""),
                title=item.get("title", ""),
                text=item.get("text", "") or "",
                source="exa_contents",
                raw=item,
            )
        )
    return out
