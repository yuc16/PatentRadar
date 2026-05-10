"""Relevance ranking helpers used before the truncate step in evidence_worker.

Truncation without ranking is "first-come-first-served": queries fired earlier
flood the budget and crowd out late-but-specific queries. Rank by keyword-hit
density first, then truncate to keep the most relevant survivors.
"""

from __future__ import annotations

from collections.abc import Iterable

from patentradar.schemas import SearchResult


def _normalize(text: str) -> str:
    return (text or "").lower()


def _keyword_hits(haystack: str, keywords: Iterable[str]) -> int:
    haystack = _normalize(haystack)
    if not haystack:
        return 0
    hits = 0
    for kw in keywords:
        kw_norm = _normalize(kw)
        if not kw_norm:
            continue
        # Count occurrences (cap at 3 per keyword so 1 long keyword doesn't
        # dominate the score from a single repeated phrase).
        hits += min(haystack.count(kw_norm), 3)
    return hits


def rank_search_results(
    results: list[SearchResult],
    *,
    keywords: Iterable[str],
) -> list[SearchResult]:
    """Sort results by relevance to keywords, descending. Stable for ties so
    the original ordering (and provider mix) is preserved within a score band."""
    keywords = list(keywords)
    if not keywords:
        return list(results)

    def score(result: SearchResult) -> int:
        haystack = f"{result.title or ''} {result.snippet or ''}"
        return _keyword_hits(haystack, keywords)

    indexed = list(enumerate(results))
    indexed.sort(key=lambda pair: (-score(pair[1]), pair[0]))
    return [item for _, item in indexed]


def rank_pages_by_relevance(
    pages: list[dict[str, str]],
    *,
    keywords: Iterable[str],
) -> list[dict[str, str]]:
    """Rank fetched pages by keyword-hit density (hits per 1000 chars)."""
    keywords = list(keywords)
    if not keywords:
        return list(pages)

    def density(page: dict[str, str]) -> float:
        text = page.get("text") or ""
        title = page.get("title") or ""
        haystack = f"{title} {text}"
        hits = _keyword_hits(haystack, keywords)
        per_1k = (hits / max(1, len(text))) * 1000
        # Tiebreaker: title hits matter more than tail text hits.
        title_hits = _keyword_hits(title, keywords)
        return per_1k + title_hits * 0.5

    indexed = list(enumerate(pages))
    indexed.sort(key=lambda pair: (-density(pair[1]), pair[0]))
    return [item for _, item in indexed]
