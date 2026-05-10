"""Search-result post-filtering: static blacklist + dynamic applicant signals."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from patentradar.schemas import ApplicantSelfSignals, SearchResult

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "search_filters.toml"


@dataclass(frozen=True)
class StaticFilters:
    domains: frozenset[str]
    path_substrings: tuple[str, ...]
    title_substrings: tuple[str, ...]
    url_regex: tuple[re.Pattern[str], ...]


@lru_cache(maxsize=1)
def _load_static_filters() -> StaticFilters:
    if not _CONFIG_PATH.exists():
        return StaticFilters(frozenset(), (), (), ())
    with _CONFIG_PATH.open("rb") as fh:
        cfg = tomllib.load(fh)
    domains: set[str] = set()
    for group in (cfg.get("domains") or {}).values():
        domains.update(d.strip().lower() for d in group)
    paths: list[str] = []
    for group in (cfg.get("path_substrings") or {}).values():
        paths.extend(group)
    titles: list[str] = []
    for group in (cfg.get("title_substrings") or {}).values():
        titles.extend(group)
    regex_patterns: list[re.Pattern[str]] = []
    for group in (cfg.get("url_regex") or {}).values():
        regex_patterns.extend(re.compile(pattern, re.IGNORECASE) for pattern in group)
    return StaticFilters(
        domains=frozenset(domains),
        path_substrings=tuple(paths),
        title_substrings=tuple(titles),
        url_regex=tuple(regex_patterns),
    )


def static_excluded_domains() -> list[str]:
    """Return the static domain list for providers that accept native excludeDomains
    (e.g. Exa)."""
    return sorted(_load_static_filters().domains)


def filter_search_results(
    results: list[SearchResult],
    *,
    self_signals: ApplicantSelfSignals | None = None,
) -> tuple[list[SearchResult], list[dict[str, str]]]:
    """Drop results that look like applicant-owned, patent-document, or malformed.

    Returns (kept, dropped). `dropped` is a list of {url, reason} dicts so the
    caller can log/inspect what was filtered without re-running the rules.
    """
    static = _load_static_filters()
    dynamic_domains = {d.strip().lower() for d in (self_signals.domains if self_signals else [])}
    dynamic_aliases = [
        a.strip().lower()
        for a in (
            (self_signals.aliases_zh if self_signals else [])
            + (self_signals.aliases_en if self_signals else [])
        )
        if a.strip()
    ]
    kept: list[SearchResult] = []
    dropped: list[dict[str, str]] = []
    for result in results:
        reason = _drop_reason(
            result=result,
            static=static,
            dynamic_domains=dynamic_domains,
            dynamic_aliases=dynamic_aliases,
        )
        if reason is None:
            kept.append(result)
        else:
            dropped.append({"url": result.url, "reason": reason})
    return kept, dropped


def _drop_reason(
    *,
    result: SearchResult,
    static: StaticFilters,
    dynamic_domains: set[str],
    dynamic_aliases: list[str],
) -> str | None:
    host = (urlparse(result.url).hostname or "").lower()
    path = (urlparse(result.url).path or "").lower()
    title = (result.title or "").lower()

    # Static domain blacklist (host or any parent domain)
    for blocked in static.domains:
        if host == blocked or host.endswith("." + blocked):
            return f"static_domain:{blocked}"
    # Dynamic applicant-owned domains
    for blocked in dynamic_domains:
        if host == blocked or host.endswith("." + blocked):
            return f"applicant_domain:{blocked}"
    # Patent-document path patterns
    for piece in static.path_substrings:
        if piece.lower() in path:
            return f"patent_path:{piece}"
    # Patent / applicant title hints
    for piece in static.title_substrings:
        if piece.lower() in title:
            return f"static_title:{piece}"
    for alias in dynamic_aliases:
        if alias and alias in title:
            return f"applicant_alias:{alias}"
    # Malformed / parasitic URL patterns
    for pattern in static.url_regex:
        if pattern.search(result.url):
            return f"url_regex:{pattern.pattern}"
    return None
