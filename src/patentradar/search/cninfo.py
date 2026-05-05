"""巨潮资讯（cninfo.com.cn）公告全文检索。

PRD 角色：A 股 / 港股上市公司年报、招股书、公告原文中提及的产品 / 技术披露。
- 无需 API key（公开网页接口）
- 返回的 ``announcementContent`` 已含正文高亮片段，可直接作为 snippet
- ``adjunctUrl`` 是相对路径，拼 ``static.cninfo.com.cn`` 即得 PDF 直链
"""

from __future__ import annotations

import re

import httpx

from .base import SearchError, SearchHit

API_URL = "http://www.cninfo.com.cn/new/fulltextSearch/full"
PDF_BASE = "http://static.cninfo.com.cn/"
DEFAULT_TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    " AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Referer": "http://www.cninfo.com.cn/new/fulltextSearch",
    "Accept": "application/json, text/plain, */*",
}
_EM_RE = re.compile(r"</?em>")


def _strip_em(s: str) -> str:
    return _EM_RE.sub("", s or "")


def search(query: str, *, num: int = 10) -> list[SearchHit]:
    """巨潮资讯全文检索。

    Args:
        query: 自由文本（公司名 / 产品名 / 技术词，空格分隔即多关键词 AND）。
        num: 期望返回条数（API 单页 10 条，超出会翻页拼接，上限 30）。
    """
    want = max(1, min(num, 30))
    hits: list[SearchHit] = []
    seen: set[str] = set()
    page = 1
    while len(hits) < want and page <= 3:
        params = {
            "searchkey": query,
            "sdate": "",
            "edate": "",
            "isfulltext": "true",
            "sortName": "pubdate",
            "sortType": "desc",
            "pageNum": str(page),
        }
        try:
            r = httpx.get(
                API_URL,
                params=params,
                headers=HEADERS,
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            raise SearchError("cninfo", str(exc)) from exc
        except ValueError as exc:
            raise SearchError("cninfo", f"响应不是 JSON: {exc}") from exc

        announcements = data.get("announcements") or []
        if not announcements:
            break
        for item in announcements:
            adj = item.get("adjunctUrl") or ""
            if not adj:
                continue
            url = PDF_BASE + adj
            if url in seen:
                continue
            seen.add(url)
            sec_name = item.get("secName") or ""
            sec_code = item.get("secCode") or ""
            title = _strip_em(item.get("announcementTitle") or "")
            snippet = _strip_em(item.get("announcementContent") or "")
            # 给 snippet 加上公司前缀，方便后续 LLM 识别
            prefixed_snippet = f"[{sec_name}({sec_code})] {snippet}" if snippet else f"{sec_name}({sec_code})"
            hits.append(
                SearchHit(
                    url=url,
                    title=f"{sec_name}：{title}" if title else sec_name,
                    snippet=prefixed_snippet[:400],
                    source="cninfo",
                    raw=item,
                    published_date=_format_ts(item.get("announcementTime")),
                )
            )
            if len(hits) >= want:
                break
        if not data.get("hasMore"):
            break
        page += 1
    return hits


def _format_ts(ms: int | None) -> str | None:
    if not ms:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None
