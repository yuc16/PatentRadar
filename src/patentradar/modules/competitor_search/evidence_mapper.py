"""Step 4 candidate evidence mapping.

Two LLM rounds per batch:
- Round 1 (initial): evaluate based on initial evidence (step3 source_urls +
  template-driven initial queries). LLM emits `suggested_followup_queries` per
  gap feature.
- Gap search: code side runs LLM-suggested queries (preferred over the older
  mechanical template). Fallback to mechanical template only if LLM gave none.
- Round 2 (gap-driven): with new evidence merged in, LLM gives finalized
  judgments and clears `suggested_followup_queries`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.fetcher.web_fetcher import fetch_evidence
from patentradar.llm.workers.evidence_worker import judge_candidate_batch
from patentradar.schemas import (
    ApplicantSelfSignals,
    Candidate,
    CandidateEvidence,
    ClaimFeature,
    EvidenceBatchResult,
    SearchResult,
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

logger = logging.getLogger(__name__)

# Per-candidate cap on how many gap-search queries we'll run in round 2.
# LLM can suggest up to ~15 across 7 features (3 per gap feature), but we
# cap at 5 to keep the search-API budget bounded.
PER_CANDIDATE_GAP_QUERY_CAP = 5


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
    search_router = router or SearchRouter(country_code=task_package.patent.country_code)
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
        is_gap_round=False,
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
        candidate = next(c for c in candidates if c.candidate_id == item.candidate.candidate_id)
        initial_context = next(
            ctx for ctx in initial_contexts if ctx.candidate.candidate_id == candidate.candidate_id
        )

        # Prefer LLM-suggested gap queries (recurrent round 1 output). Fall
        # back to the mechanical template only if LLM gave nothing.
        llm_queries = _collect_llm_suggested_queries(item, cap=PER_CANDIDATE_GAP_QUERY_CAP)
        if llm_queries:
            logger.info(
                "module2 gap %s candidate=%s LLM-driven queries=%d",
                batch_id, candidate.candidate_id, len(llm_queries),
            )
            gap_context = _gap_context_from_queries(
                publication_no=task_package.patent.publication_no,
                candidate=candidate,
                claim_features=task_package.claim_1_features,
                queries=llm_queries,
                router=search_router,
                self_signals=self_signals,
            )
        else:
            gap_features = _gap_features(item=item, claim_features=task_package.claim_1_features)
            if not gap_features:
                continue
            logger.info(
                "module2 gap %s candidate=%s fallback to mechanical template",
                batch_id, candidate.candidate_id,
            )
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
            is_gap_round=True,
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
    is_gap_round: bool,
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
        is_gap_round=is_gap_round,
        model=model,
        reasoning_effort=reasoning_effort,
    )


def _collect_llm_suggested_queries(item: CandidateEvidence, *, cap: int) -> list[str]:
    """Collect dedupe'd LLM-suggested queries from a CandidateEvidence."""
    seen: set[str] = set()
    out: list[str] = []
    for comparison in item.comparisons:
        for q in comparison.suggested_followup_queries:
            q = q.strip()
            if not q or q in seen:
                continue
            seen.add(q)
            out.append(q)
            if len(out) >= cap:
                return out
    return out


def _gap_context_from_queries(
    *,
    publication_no: str,
    candidate: Candidate,
    claim_features: list[ClaimFeature],
    queries: list[str],
    router: SearchRouter,
    self_signals: ApplicantSelfSignals | None,
) -> CandidateEvidenceContext:
    """Build a CandidateEvidenceContext from a pre-supplied query list (LLM-driven gap)."""
    results = router.search_queries(
        publication_no=publication_no,
        queries=queries,
        query_id_prefix=f"{candidate.candidate_id}-GL",
        max_results_per_query=5,
        self_signals=self_signals,
    ).results
    pages, images = _fetch_pages_for_results(
        candidate=candidate, claim_features=claim_features, results=results, max_pages=8
    )
    return CandidateEvidenceContext(
        candidate=candidate,
        queries=list(queries),
        search_results=results,
        fetched_pages=pages,
        fetched_images=images,
    )


def _fetch_pages_for_results(
    *,
    candidate: Candidate,
    claim_features: list[ClaimFeature],
    results: list[SearchResult],
    max_pages: int,
) -> tuple[list[dict[str, str]], list[dict]]:
    keywords: list[str] = [
        candidate.company,
        candidate.company_en,
        candidate.product_name,
        candidate.product_name_en,
        candidate.product_version,
        *[feature.feature_text[:24] for feature in claim_features],
    ]
    keywords = [k for k in keywords if k and k.strip()]
    pages: list[dict[str, str]] = []
    images: list[dict] = []
    seen_urls: set[str] = set()
    for result in results:
        if result.url in seen_urls:
            continue
        seen_urls.add(result.url)
        evidence = fetch_evidence(result.url, keywords=keywords, max_chars=6000)
        if evidence is None:
            continue
        if evidence.text:
            pages.append(
                {
                    "url": evidence.url,
                    "title": evidence.title or result.title,
                    "text": evidence.text[:6000],
                }
            )
        for image_bytes in evidence.images:
            images.append(
                {"url": evidence.url, "title": evidence.title or result.title, "png": image_bytes}
            )
        if len(pages) >= max_pages:
            break
    return pages, images


def _gap_features(*, item: CandidateEvidence, claim_features: list[ClaimFeature]) -> list[ClaimFeature]:
    """Fallback gap-feature identification when LLM didn't suggest any queries."""
    features_by_id = {feature.feature_id: feature for feature in claim_features}
    gaps: list[ClaimFeature] = []
    for comparison in item.comparisons:
        if comparison.status in {"证据不足", "可能满足"} or len({evidence.url for evidence in comparison.evidence}) < 2:
            feature = features_by_id.get(comparison.feature_id)
            if feature is not None:
                gaps.append(feature)
    return gaps
