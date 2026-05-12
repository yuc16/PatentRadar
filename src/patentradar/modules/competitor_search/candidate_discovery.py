"""Step 2 search execution."""

from __future__ import annotations

from patentradar.schemas import QueryPlan, SearchResultsArtifact
from patentradar.search import SearchRouter


def discover_candidates(
    *,
    publication_no: str,
    query_plan: QueryPlan,
    router: SearchRouter | None = None,
    country_code: str = "",
) -> SearchResultsArtifact:
    search_router = router or SearchRouter(country_code=country_code)
    return search_router.search_query_plan(publication_no=publication_no, query_plan=query_plan)
