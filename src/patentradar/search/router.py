"""Search routing across Tavily, Bocha, Exa, and Brave."""

from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from patentradar.schemas import (
    ApplicantSelfSignals,
    QueryPlan,
    SearchProviderName,
    SearchQuery,
    SearchResult,
    SearchResultsArtifact,
)

from .base import SearchProvider
from .bocha import BochaProvider
from .brave import BraveProvider
from .exa import ExaProvider
from .filters import filter_search_results
from .result_normalizer import canonical_url
from .tavily import TavilyProvider

logger = logging.getLogger(__name__)


class SearchRouter:
    """Runs each query against one or more available search providers."""

    def __init__(self, providers: Iterable[SearchProvider] | None = None) -> None:
        provider_list = list(providers) if providers is not None else [
            TavilyProvider(),
            BochaProvider(),
            ExaProvider(),
            BraveProvider(),
        ]
        self.providers = {provider.name: provider for provider in provider_list}

    def search_query_plan(
        self,
        *,
        publication_no: str,
        query_plan: QueryPlan,
        max_results_per_query: int = 5,
        target_max_results: int = 400,
        max_providers_per_query: int = 3,
        self_signals: ApplicantSelfSignals | None = None,
    ) -> SearchResultsArtifact:
        """Run every query against up to `max_providers_per_query` providers.

        Two correctness rules vs the previous implementation:
        - The global cap is raised so all 30-50 plan queries get to run.
        - For each query we visit at most `max_providers_per_query` providers
          (in `preferred_providers` order). This stops a high-yield query from
          eating the budget and starving later, more specific queries — the
          earlier code unconditionally exhausted every provider per query.
        """
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for query in query_plan.queries:
            if len(results) >= target_max_results:
                break
            providers_visited = 0
            for provider_name in self._providers_for_query(query):
                if providers_visited >= max_providers_per_query:
                    break
                provider = self.providers.get(provider_name)
                if provider is None:
                    continue
                providers_visited += 1
                try:
                    provider_results = provider.search(
                        query_id=query.query_id,
                        query=query.query,
                        max_results=max_results_per_query,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("Search failed provider=%s query_id=%s error=%s", provider_name, query.query_id, exc)
                    continue
                for result in provider_results:
                    url_key = canonical_url(result.url)
                    if url_key in seen_urls:
                        continue
                    seen_urls.add(url_key)
                    results.append(result)
                    if len(results) >= target_max_results:
                        break
                if len(results) >= target_max_results:
                    break
        kept, dropped = filter_search_results(
            results,
            self_signals=self_signals or query_plan.applicant_self_signals,
        )
        if dropped:
            logger.info(
                "search filter dropped %d/%d results (top reasons: %s)",
                len(dropped), len(results), _top_reasons(dropped, 5),
            )
        return SearchResultsArtifact(publication_no=publication_no, results=kept)

    def search_queries(
        self,
        *,
        publication_no: str,
        queries: list[str],
        query_id_prefix: str,
        max_results_per_query: int = 5,
        self_signals: ApplicantSelfSignals | None = None,
    ) -> SearchResultsArtifact:
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for query_index, query_text in enumerate(queries, start=1):
            query = SearchQuery(
                query_id=f"Q{query_index:02d}",
                query=query_text,
                intent="evidence",
                language="mixed",
                preferred_providers=["bocha", "brave", "tavily", "exa"],
            )
            for provider_name in self._providers_for_query(query):
                provider = self.providers.get(provider_name)
                if provider is None:
                    continue
                try:
                    provider_results = provider.search(
                        query_id=query.query_id,
                        query=query.query,
                        max_results=max_results_per_query,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("Evidence search failed provider=%s query=%s error=%s", provider_name, query_text, exc)
                    continue
                for result in provider_results:
                    url_key = canonical_url(result.url)
                    if url_key in seen_urls:
                        continue
                    seen_urls.add(url_key)
                    result.result_id = f"{query_id_prefix}-{len(results) + 1:03d}"
                    results.append(result)
        kept, dropped = filter_search_results(results, self_signals=self_signals)
        if dropped:
            logger.info(
                "evidence search filter dropped %d/%d results (top reasons: %s)",
                len(dropped), len(results), _top_reasons(dropped, 5),
            )
        return SearchResultsArtifact(publication_no=publication_no, results=kept)

    def _providers_for_query(self, query: SearchQuery) -> list[SearchProviderName]:
        ordered = query.preferred_providers or self._default_providers(query)
        return [provider for provider in ordered if provider in self.providers]

    def _default_providers(self, query: SearchQuery) -> list[SearchProviderName]:
        if query.language == "zh":
            return ["bocha", "brave", "tavily"]
        if query.language == "en":
            return ["exa", "tavily", "brave"]
        return ["bocha", "tavily", "exa", "brave"]


def _top_reasons(dropped: list[dict[str, str]], n: int) -> str:
    from collections import Counter
    counter = Counter(item["reason"] for item in dropped)
    return ", ".join(f"{reason}={count}" for reason, count in counter.most_common(n))
