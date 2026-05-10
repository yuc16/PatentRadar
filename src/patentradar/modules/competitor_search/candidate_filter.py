"""Step 3 candidate filtering."""

from __future__ import annotations

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.llm.workers.candidate_worker import filter_candidates
from patentradar.schemas import CandidateShortlist, SearchResultsArtifact, TaskPackage


def shortlist_candidates(
    *,
    task_package: TaskPackage,
    search_results: SearchResultsArtifact,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> CandidateShortlist:
    return filter_candidates(
        task_package=task_package,
        search_results=search_results,
        model=model,
        reasoning_effort=reasoning_effort,
    )
