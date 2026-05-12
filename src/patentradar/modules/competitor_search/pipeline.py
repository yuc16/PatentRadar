"""Module-two competitor search pipeline."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.schemas import (
    CandidateEvidence,
    CandidateShortlist,
    EvidenceBatchResult,
    QueryPlan,
    SearchResultsArtifact,
    TaskPackage,
    TopCompetitorReport,
)

from .candidate_discovery import discover_candidates
from .candidate_filter import shortlist_candidates
from .evidence_mapper import map_evidence_for_batch
from .query_generator import build_query_plan
from .scorer import rank_top_competitors

logger = logging.getLogger(__name__)


def run_competitor_search(
    *,
    task_package_path: Path,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    max_workers: int = 3,
) -> TopCompetitorReport:
    task_package = load_task_package(task_package_path)
    query_plan = run_step1_generate_queries(
        task_package=task_package,
        output_dir=output_dir,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    search_results = run_step2_search_results(
        task_package=task_package,
        query_plan=query_plan,
        output_dir=output_dir,
    )
    shortlist = run_step3_filter_candidates(
        task_package=task_package,
        search_results=search_results,
        output_dir=output_dir,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    evidence_results = run_step4_map_evidence(
        task_package=task_package,
        shortlist=shortlist,
        output_dir=output_dir,
        query_plan=query_plan,
        model=model,
        reasoning_effort=reasoning_effort,
        max_workers=max_workers,
    )
    return run_step5_rank_top(
        task_package=task_package,
        evidence_results=evidence_results,
        output_dir=output_dir,
    )


def run_step1_generate_queries(
    *,
    task_package: TaskPackage,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> QueryPlan:
    start = time.perf_counter()
    query_plan = build_query_plan(
        task_package,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    _write_json(output_dir / "step1_query_plan.json", query_plan.model_dump())
    logger.info(
        "module2 step1 publication=%s query_count=%d elapsed_ms=%d",
        task_package.patent.publication_no,
        len(query_plan.queries),
        _elapsed_ms(start),
    )
    return query_plan


def run_step2_search_results(
    *,
    task_package: TaskPackage,
    query_plan: QueryPlan,
    output_dir: Path,
) -> SearchResultsArtifact:
    start = time.perf_counter()
    search_results = discover_candidates(
        publication_no=task_package.patent.publication_no,
        query_plan=query_plan,
        country_code=task_package.patent.country_code,
    )
    _write_json(output_dir / "step2_search_results.json", search_results.model_dump())
    logger.info(
        "module2 step2 publication=%s result_count=%d elapsed_ms=%d",
        task_package.patent.publication_no,
        len(search_results.results),
        _elapsed_ms(start),
    )
    return search_results


def run_step3_filter_candidates(
    *,
    task_package: TaskPackage,
    search_results: SearchResultsArtifact,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> CandidateShortlist:
    start = time.perf_counter()
    shortlist = shortlist_candidates(
        task_package=task_package,
        search_results=search_results,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    _write_json(output_dir / "step3_candidate_shortlist.json", shortlist.model_dump())
    logger.info(
        "module2 step3 publication=%s candidate_count=%d elapsed_ms=%d",
        task_package.patent.publication_no,
        len(shortlist.candidates),
        _elapsed_ms(start),
    )
    return shortlist


def run_step4_map_evidence(
    *,
    task_package: TaskPackage,
    shortlist: CandidateShortlist,
    output_dir: Path,
    query_plan: QueryPlan | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    max_workers: int = 3,
) -> list[CandidateEvidence]:
    start = time.perf_counter()
    self_signals = query_plan.applicant_self_signals if query_plan else None
    batches = [
        shortlist.candidates[index : index + 5]
        for index in range(0, len(shortlist.candidates), 5)
    ]
    batch_dir = output_dir / "step4_evidence_batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    batch_results: list[EvidenceBatchResult] = []
    worker_count = max(1, min(max_workers, len(batches)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                map_evidence_for_batch,
                task_package=task_package,
                candidates=batch,
                batch_id=f"B{batch_index:02d}",
                self_signals=self_signals,
                model=model,
                reasoning_effort=reasoning_effort,
            ): batch_index
            for batch_index, batch in enumerate(batches, start=1)
        }
        for future in as_completed(futures):
            batch_index = futures[future]
            result = future.result()
            batch_results.append(result)
            _write_json(batch_dir / f"batch_{batch_index:02d}.json", result.model_dump())

    batch_results.sort(key=lambda item: item.batch_id)
    evidence_results = [item for batch in batch_results for item in batch.results]
    _write_json(
        output_dir / "step4_candidate_evidence.json",
        {
            "publication_no": task_package.patent.publication_no,
            "results": [item.model_dump() for item in evidence_results],
        },
    )
    logger.info(
        "module2 step4 publication=%s evaluated_count=%d elapsed_ms=%d",
        task_package.patent.publication_no,
        len(evidence_results),
        _elapsed_ms(start),
    )
    return evidence_results


def run_step5_rank_top(
    *,
    task_package: TaskPackage,
    evidence_results: list[CandidateEvidence],
    output_dir: Path,
) -> TopCompetitorReport:
    start = time.perf_counter()
    report = rank_top_competitors(
        publication_no=task_package.patent.publication_no,
        candidates=evidence_results,
        top_n=5,
    )
    _write_json(output_dir / "step5_top5_claim1_candidates.json", report.model_dump())
    logger.info(
        "module2 step5 publication=%s top_count=%d excluded_count=%d elapsed_ms=%d",
        task_package.patent.publication_no,
        len(report.top_competitors),
        len(report.excluded_candidates),
        _elapsed_ms(start),
    )
    return report


def load_task_package(path: Path) -> TaskPackage:
    return TaskPackage.model_validate(_read_json(path))


def load_query_plan(path: Path) -> QueryPlan:
    return QueryPlan.model_validate(_read_json(path))


def load_search_results(path: Path) -> SearchResultsArtifact:
    return SearchResultsArtifact.model_validate(_read_json(path))


def load_candidate_shortlist(path: Path) -> CandidateShortlist:
    return CandidateShortlist.model_validate(_read_json(path))


def load_candidate_evidence(path: Path) -> list[CandidateEvidence]:
    data = _read_json(path)
    return [CandidateEvidence.model_validate(item) for item in data.get("results", [])]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
