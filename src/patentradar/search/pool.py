"""共享证据检索工具池（PRD §7.3）。

- ``search(query, engines=...)`` 多引擎并行搜索 + URL 黑名单 + 去重合并。
- ``read_url(url)`` 抽取 URL 正文（Tavily Extract → Exa Contents 兜底链）。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from . import bocha, brave, cninfo, exa, tavily
from .base import ExtractedPage, SearchError, SearchHit

logger = logging.getLogger(__name__)

# cninfo 是中文专项引擎，默认不进通用召回（普通 query 在年报里噪声大）；
# 但 DeepSeek Agent 在已知候选公司名时会显式调用它做证据补搜。
ALL_SEARCH_ENGINES = ("bocha", "exa", "brave", "tavily", "cninfo")
DEFAULT_SEARCH_ENGINES = ("bocha", "exa", "brave", "tavily")

# 默认 URL 黑名单：这些站点的搜索结果几乎都是其他人的专利文献 / 论文，不是真实竞品产品资料。
# 在召回阶段直接过滤，省下后续 LLM 筛选 token。
DEFAULT_EXCLUDE_DOMAINS = (
    "patents.google.com",
    "patentscope.wipo.int",
    "patents.com",
    "patentsdb.com",
    "max.book118.com",
    "book118.com",
    "docin.com",
    "doc88.com",
    "xjishu.com",
    "zhuanlichaxun.net",
    "soopat.com",
    "drugfuture.com",
    "ip.com",
)


def _is_excluded(url: str, exclude_domains: tuple[str, ...]) -> bool:
    if not url:
        return True
    low = url.lower()
    return any(dom in low for dom in exclude_domains)


def search(
    query: str,
    *,
    engines: list[str] | tuple[str, ...] = DEFAULT_SEARCH_ENGINES,
    num_per_engine: int = 8,
    exclude_domains: tuple[str, ...] = DEFAULT_EXCLUDE_DOMAINS,
) -> list[SearchHit]:
    """并行调用多个搜索引擎，按 URL 去重 + 黑名单过滤，保留首次出现的源信息。"""
    fns: dict[str, Callable[[], list[SearchHit]]] = {
        "bocha": lambda: bocha.search(query, num=num_per_engine),
        "exa": lambda: exa.search(query, num=num_per_engine),
        "brave": lambda: brave.search(query, num=num_per_engine),
        "tavily": lambda: tavily.search(query, num=num_per_engine),
        "cninfo": lambda: cninfo.search(query, num=num_per_engine),
    }
    selected = [e for e in engines if e in fns]

    aggregated: dict[str, SearchHit] = {}
    sources_per_url: dict[str, list[str]] = {}

    with ThreadPoolExecutor(max_workers=len(selected) or 1) as ex:
        futures = {ex.submit(fns[name]): name for name in selected}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                hits = fut.result()
            except SearchError as exc:
                logger.warning("search engine failed: %s", exc)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("search engine %s 异常: %s", name, exc)
                continue
            for h in hits:
                if not h.url or _is_excluded(h.url, exclude_domains):
                    continue
                sources_per_url.setdefault(h.url, []).append(name)
                if h.url not in aggregated:
                    aggregated[h.url] = h

    merged: list[SearchHit] = []
    for url, h in aggregated.items():
        h.raw = {**h.raw, "_sources": sources_per_url[url]}
        merged.append(h)
    return merged


def read_url(url: str) -> ExtractedPage:
    """正文抽取兜底链：tavily_extract → exa_contents。"""
    last_exc: Exception | None = None
    try:
        pages = tavily.extract([url])
        if pages and pages[0].text.strip():
            return pages[0]
    except Exception as exc:  # noqa: BLE001
        last_exc = exc
    try:
        pages = exa.contents([url])
        if pages and pages[0].text.strip():
            return pages[0]
    except Exception as exc:  # noqa: BLE001
        last_exc = exc
    raise SearchError("read_url", f"所有 reader 均失败: {last_exc}")
