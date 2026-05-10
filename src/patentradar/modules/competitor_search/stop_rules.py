"""Stop rules for candidate evidence searches."""

from __future__ import annotations

from patentradar.schemas import CandidateEvidence, SearchResult


def feature_has_enough_evidence(item: CandidateEvidence, *, min_urls: int = 2) -> bool:
    for comparison in item.comparisons:
        if comparison.status != "明确满足":
            return False
        urls = {evidence.url for evidence in comparison.evidence}
        if len(urls) < min_urls:
            return False
    return True


def too_many_duplicate_sources(results: list[SearchResult], *, duplicate_ratio: float = 0.7) -> bool:
    if len(results) < 8:
        return False
    unique_urls = {result.url for result in results}
    return 1 - (len(unique_urls) / len(results)) >= duplicate_ratio
