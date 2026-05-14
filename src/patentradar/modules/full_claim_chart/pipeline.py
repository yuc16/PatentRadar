"""Module three full claim-chart pipeline.

Per-candidate flow (5 TOP candidates × 2 LLM rounds each = ~10 LLM calls/patent):

  Round 1:
    Input: task_package (all claims) + module-two CandidateEvidence
           + module-two evidence pool (URLs / fetched text / images)
    LLM evaluates every feature using existing evidence + emits
    `suggested_followup_queries` for gap features
  ↓
  Gap search:
    Code side runs the LLM-suggested queries (claim-1 priority, ≤30 total).
    For each new search result, fetch page text + PDF key-page images.
    Merge into the candidate's evidence pool.
  ↓
  Round 2:
    Same prompt, is_finalization_round=True, includes new evidence.
    LLM outputs finalized FullClaimChartCandidate (suggested_followup_queries=[]).
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.fetcher.image_utils import dump_visual_log
from patentradar.fetcher.web_fetcher import fetch_evidence
from patentradar.llm.workers.full_claim_chart_worker import evaluate_candidate
from patentradar.schemas import (
    ApplicantSelfSignals,
    CandidateEvidence,
    FullClaimChartCandidate,
    FullClaimChartReport,
    SearchResult,
    TaskPackage,
    TopCompetitorReport,
)
from patentradar.search import SearchRouter

logger = logging.getLogger(__name__)

GAP_QUERY_HARD_CAP = 30  # per candidate total budget


def run_full_claim_chart(
    *,
    task_package: TaskPackage,
    top_report: TopCompetitorReport,
    output_dir: Path,
    self_signals: ApplicantSelfSignals | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    max_workers: int = 2,
) -> FullClaimChartReport:
    """Process every TOP candidate (non-disqualified) per-candidate, two rounds."""
    output_dir.mkdir(parents=True, exist_ok=True)
    per_candidate_dir = output_dir / "candidates"
    per_candidate_dir.mkdir(parents=True, exist_ok=True)
    # 双份落盘：fetched 是 fetcher 抓回的全集；sent 是 worker dedup+cap 后真正送 LLM 的子集
    visual_log_fetched_dir = output_dir / "visual_log_fetched"
    visual_log_sent_dir = output_dir / "visual_log_sent"
    visual_log_fetched_dir.mkdir(parents=True, exist_ok=True)
    visual_log_sent_dir.mkdir(parents=True, exist_ok=True)

    competitors_to_process = top_report.top_competitors
    completed_candidates: list[FullClaimChartCandidate] = []
    router = SearchRouter(country_code=task_package.patent.country_code)

    started = time.perf_counter()
    worker_count = max(1, min(max_workers, len(competitors_to_process)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _process_one_candidate,
                task_package=task_package,
                module_two_evidence=evidence,
                router=router,
                self_signals=self_signals,
                model=model,
                reasoning_effort=reasoning_effort,
                output_dir=per_candidate_dir,
                visual_log_dir=visual_log_fetched_dir,
                visual_log_sent_dir=visual_log_sent_dir,
            ): evidence
            for evidence in competitors_to_process
        }
        for future in as_completed(futures):
            result = future.result()
            completed_candidates.append(result)

    # Preserve original ranking order (by candidate_id in top_report)
    candidate_order = {c.candidate.candidate_id: idx for idx, c in enumerate(competitors_to_process)}
    completed_candidates.sort(key=lambda fc: candidate_order.get(fc.candidate.candidate_id, 999))

    report = FullClaimChartReport(
        publication_no=task_package.patent.publication_no,
        top_competitors=[c for c in completed_candidates if not c.disqualified],
        excluded_candidates=[c for c in completed_candidates if c.disqualified],
    )
    _write_json(output_dir / "top5_full_claim_chart.json", report.model_dump())
    logger.info(
        "module3 full_claim_chart publication=%s top=%d excluded=%d elapsed_ms=%d",
        task_package.patent.publication_no,
        len(report.top_competitors),
        len(report.excluded_candidates),
        int((time.perf_counter() - started) * 1000),
    )
    return report


def _process_one_candidate(
    *,
    task_package: TaskPackage,
    module_two_evidence: CandidateEvidence,
    router: SearchRouter,
    self_signals: ApplicantSelfSignals | None,
    model: str,
    reasoning_effort: str,
    output_dir: Path,
    visual_log_dir: Path | None = None,
    visual_log_sent_dir: Path | None = None,
) -> FullClaimChartCandidate:
    candidate_id = module_two_evidence.candidate.candidate_id
    started = time.perf_counter()
    logger.info("module3 candidate=%s start", candidate_id)

    # Initial evidence pool reuses everything module two collected.
    pool_pages = _evidence_pool_from_module_two(module_two_evidence)
    pool_images: list[dict] = []  # module-two image bytes are not stored in TopCompetitorReport
    pool_url_set = {page["url"] for page in pool_pages}

    # Round 1: identify gaps, get suggested_followup_queries
    round1 = evaluate_candidate(
        task_package=task_package,
        candidate=module_two_evidence.candidate,
        module_two_evidence=module_two_evidence,
        evidence_pool_pages=pool_pages,
        evidence_pool_images=pool_images,
        new_search_results=[],
        is_finalization_round=False,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    _write_json(output_dir / f"{candidate_id}_round1.json", round1.model_dump())

    # 失格短路：round 1 已判 disqualified（权 1 任一特征明确不满足或 launch_date
    # 早于专利申请日）→ 跳过 round 2，节省一次 vision LLM 调用。
    if round1.disqualified:
        logger.info(
            "module3 candidate=%s round1 disqualified=%s, skipping round 2",
            candidate_id, round1.disqualification_reason,
        )
        return round1

    suggested_queries = _collect_suggested_queries(
        round1,
        hard_cap=GAP_QUERY_HARD_CAP,
        already_tried=list(module_two_evidence.searched_queries),
    )
    new_search_results: list[SearchResult] = []
    if suggested_queries:
        logger.info("module3 candidate=%s round1 -> %d gap queries", candidate_id, len(suggested_queries))
        new_search_results = router.search_queries(
            publication_no=task_package.patent.publication_no,
            queries=suggested_queries,
            query_id_prefix=f"{candidate_id}-M3",
            max_results_per_query=4,
            self_signals=self_signals,
        ).results
        new_pages, new_images = _fetch_new_evidence(
            results=new_search_results,
            keywords=_keywords_from_round1(round1),
            pool_url_set=pool_url_set,
            max_pages=8,
        )
        pool_pages.extend(new_pages)
        pool_images.extend(new_images)
        pool_url_set.update(page["url"] for page in new_pages)

    # Round 2: finalize
    round2 = evaluate_candidate(
        task_package=task_package,
        candidate=module_two_evidence.candidate,
        module_two_evidence=module_two_evidence,
        evidence_pool_pages=pool_pages,
        evidence_pool_images=pool_images,
        new_search_results=new_search_results,
        is_finalization_round=True,
        model=model,
        reasoning_effort=reasoning_effort,
        visual_log_sent_dir=visual_log_sent_dir,
        visual_log_candidate_id=candidate_id,
    )
    _write_json(output_dir / f"{candidate_id}_round2.json", round2.model_dump())

    if visual_log_dir is not None:
        dump_visual_log(visual_log_dir, candidate_id, pool_images)

    logger.info(
        "module3 candidate=%s done total_score=%.2f claim_1_score=%.2f elapsed_ms=%d",
        candidate_id,
        round2.total_score,
        round2.claim_1_score,
        int((time.perf_counter() - started) * 1000),
    )
    return round2


def _evidence_pool_from_module_two(module_two_evidence: CandidateEvidence) -> list[dict[str, str]]:
    """Reconstruct page-like dicts from the evidence URLs found in module two.

    We only have the (url, snippet, source_name, title) shape from
    `EvidenceSource`; for module three we need {url, title, text}. Use snippet
    as the text since the raw fetched_pages aren't persisted by module two —
    this is a pragmatic limitation. Module three may re-fetch via gap search.
    """
    pages: list[dict[str, str]] = []
    seen: set[str] = set()
    for comparison in module_two_evidence.comparisons:
        for ev in comparison.evidence:
            if ev.url in seen:
                continue
            seen.add(ev.url)
            pages.append(
                {
                    "url": ev.url,
                    "title": ev.title or "",
                    "text": ev.snippet or "",
                }
            )
    for ev in module_two_evidence.launch_date_evidence:
        if ev.url in seen:
            continue
        seen.add(ev.url)
        pages.append(
            {
                "url": ev.url,
                "title": ev.title or "",
                "text": ev.snippet or "",
            }
        )
    return pages


def _collect_suggested_queries(
    round1: FullClaimChartCandidate,
    *,
    hard_cap: int,
    already_tried: list[str] | None = None,
) -> list[str]:
    """Collect LLM-suggested queries across all features, dedupe + drop any
    already covered by module two's earlier searched_queries (case-insensitive
    + trimmed), respect cap."""
    seen: set[str] = set()
    # Module-two history dedup: if module 2 already ran a literally-identical
    # query, skip it — running it again wastes a search-API call (results are
    # already in the evidence_pool URL set anyway).
    already_norm: set[str] = {
        q.strip().lower() for q in (already_tried or []) if q and q.strip()
    }
    collected: list[str] = []
    skipped_dup_with_module_two = 0
    for entry in round1.claim_charts:
        for cmp in entry.comparisons:
            for q in cmp.suggested_followup_queries:
                q = q.strip()
                if not q:
                    continue
                key = q.lower()
                if key in seen:
                    continue
                if key in already_norm:
                    skipped_dup_with_module_two += 1
                    continue
                seen.add(key)
                collected.append(q)
                if len(collected) >= hard_cap:
                    if skipped_dup_with_module_two:
                        logger.info(
                            "module3 query dedup: %d module-two duplicates skipped",
                            skipped_dup_with_module_two,
                        )
                    return collected
    if skipped_dup_with_module_two:
        logger.info(
            "module3 query dedup: %d module-two duplicates skipped",
            skipped_dup_with_module_two,
        )
    return collected


def _keywords_from_round1(round1: FullClaimChartCandidate) -> list[str]:
    keywords = [
        round1.candidate.company,
        round1.candidate.company_en,
        round1.candidate.product_name,
        round1.candidate.product_name_en,
        round1.candidate.product_version,
    ]
    # Also include head of each gap feature's patent_feature for window matching.
    for entry in round1.claim_charts:
        for cmp in entry.comparisons:
            if cmp.status in {"证据不足", "可能满足"}:
                keywords.append(cmp.patent_feature[:32])
    return [k for k in keywords if k and k.strip()]


def _fetch_new_evidence(
    *,
    results: list[SearchResult],
    keywords: list[str],
    pool_url_set: set[str],
    max_pages: int,
) -> tuple[list[dict[str, str]], list[dict]]:
    pages: list[dict[str, str]] = []
    images: list[dict] = []
    seen_in_call: set[str] = set()
    for result in results:
        if result.url in pool_url_set or result.url in seen_in_call:
            continue
        seen_in_call.add(result.url)
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
        for img in evidence.images:
            images.append(
                {
                    "url": img.src_url,
                    "title": img.alt or evidence.title or result.title,
                    "png": img.png,
                    "score": img.score,
                }
            )
        if len(pages) >= max_pages:
            break
    return pages, images


def load_task_package(path: Path) -> TaskPackage:
    return TaskPackage.model_validate(_read_json(path))


def load_top_report(path: Path) -> TopCompetitorReport:
    return TopCompetitorReport.model_validate(_read_json(path))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
