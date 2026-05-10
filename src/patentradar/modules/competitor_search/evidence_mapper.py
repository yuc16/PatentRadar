"""Step 4 candidate evidence mapping."""

from __future__ import annotations

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.llm.workers.evidence_worker import judge_candidate_batch
from patentradar.schemas import (
    ApplicantSelfSignals,
    Candidate,
    CandidateEvidence,
    ClaimFeature,
    EvidenceBatchResult,
    TaskPackage,
)
from patentradar.search import SearchRouter

from .evidence_search import (
    CandidateEvidenceContext,
    build_gap_evidence_context,
    build_initial_evidence_context,
    merge_contexts,
)
from .stop_rules import feature_has_enough_evidence


def map_evidence_for_batch(
    *,
    task_package: TaskPackage,
    candidates: list[Candidate],
    batch_id: str,
    router: SearchRouter | None = None,
    self_signals: ApplicantSelfSignals | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> EvidenceBatchResult:
    search_router = router or SearchRouter()
    initial_contexts = [
        build_initial_evidence_context(
            publication_no=task_package.patent.publication_no,
            candidate=candidate,
            claim_features=task_package.claim_1_features,
            router=search_router,
            self_signals=self_signals,
        )
        for candidate in candidates
    ]
    initial_result = _judge(
        task_package=task_package,
        contexts=initial_contexts,
        batch_id=f"{batch_id}-initial",
        model=model,
        reasoning_effort=reasoning_effort,
    )
    final_by_id: dict[str, CandidateEvidence] = {
        item.candidate.candidate_id: item for item in initial_result.results
    }

    gap_contexts: list[CandidateEvidenceContext] = []
    for item in initial_result.results:
        if item.disqualified or feature_has_enough_evidence(item):
            continue
        candidate = next(candidate for candidate in candidates if candidate.candidate_id == item.candidate.candidate_id)
        gap_features = _gap_features(item=item, claim_features=task_package.claim_1_features)
        if not gap_features:
            continue
        initial_context = next(context for context in initial_contexts if context.candidate.candidate_id == candidate.candidate_id)
        gap_context = build_gap_evidence_context(
            publication_no=task_package.patent.publication_no,
            candidate=candidate,
            gap_features=gap_features,
            router=search_router,
            self_signals=self_signals,
        )
        gap_contexts.append(merge_contexts(initial_context, gap_context))

    if gap_contexts:
        gap_result = _judge(
            task_package=task_package,
            contexts=gap_contexts,
            batch_id=f"{batch_id}-final",
            model=model,
            reasoning_effort=reasoning_effort,
        )
        for item in gap_result.results:
            final_by_id[item.candidate.candidate_id] = item

    return EvidenceBatchResult(
        publication_no=task_package.patent.publication_no,
        batch_id=batch_id,
        results=[final_by_id[candidate.candidate_id] for candidate in candidates if candidate.candidate_id in final_by_id],
    )


def _judge(
    *,
    task_package: TaskPackage,
    contexts: list[CandidateEvidenceContext],
    batch_id: str,
    model: str,
    reasoning_effort: str,
) -> EvidenceBatchResult:
    return judge_candidate_batch(
        task_package=task_package,
        candidates=[context.candidate for context in contexts],
        search_results_by_candidate={
            context.candidate.candidate_id: context.search_results for context in contexts
        },
        fetched_pages_by_candidate={
            context.candidate.candidate_id: context.fetched_pages for context in contexts
        },
        fetched_images_by_candidate={
            context.candidate.candidate_id: context.fetched_images for context in contexts
        },
        batch_id=batch_id,
        model=model,
        reasoning_effort=reasoning_effort,
    )


def _gap_features(*, item: CandidateEvidence, claim_features: list[ClaimFeature]) -> list[ClaimFeature]:
    features_by_id = {feature.feature_id: feature for feature in claim_features}
    gaps: list[ClaimFeature] = []
    for comparison in item.comparisons:
        if comparison.status in {"证据不足", "可能满足"} or len({evidence.url for evidence in comparison.evidence}) < 2:
            feature = features_by_id.get(comparison.feature_id)
            if feature is not None:
                gaps.append(feature)
    return gaps
