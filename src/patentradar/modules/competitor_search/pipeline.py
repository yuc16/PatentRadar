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

# step4 单候选 evidence 断点续传缓存的格式版本。证据 URL 白名单校验
# (_drop_empty_url_evidence allowed_urls) 是在写盘**前**做的，旧缓存里可能留有
# 编造 URL 且以满分载入，还会被模块三纳入白名单背书。bump 此版本即让所有旧缓存
# (无 _cache_version 字段或版本不符) 失效、强制重新计算。
_STEP4_CACHE_VERSION = 2


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
    cached = output_dir / "step1_query_plan.json"
    if cached.exists():
        logger.info("module2 step1 loaded_from_cache %s", cached)
        return QueryPlan.model_validate(json.loads(cached.read_text(encoding="utf-8")))
    query_plan = build_query_plan(
        task_package,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    _write_json(cached, query_plan.model_dump())
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
    cached = output_dir / "step2_search_results.json"
    if cached.exists():
        logger.info("module2 step2 loaded_from_cache %s", cached)
        return SearchResultsArtifact.model_validate(json.loads(cached.read_text(encoding="utf-8")))
    search_results = discover_candidates(
        publication_no=task_package.patent.publication_no,
        query_plan=query_plan,
        country_code=task_package.patent.country_code,
    )
    _write_json(cached, search_results.model_dump())
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
    cached = output_dir / "step3_candidate_shortlist.json"
    if cached.exists():
        logger.info("module2 step3 loaded_from_cache %s", cached)
        return CandidateShortlist.model_validate(json.loads(cached.read_text(encoding="utf-8")))
    shortlist = shortlist_candidates(
        task_package=task_package,
        search_results=search_results,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    _write_json(cached, shortlist.model_dump())
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
    max_workers: int = 1,
) -> list[CandidateEvidence]:
    """Per-candidate evidence judging. 一次 LLM 调用只处理 1 个候选；落盘后再
    跑下一个。比旧的 5-候选 batch 模式 prompt 砍到 1/5，断流/server_error 概率
    骤降；早期淘汰（权 1 任一特征明确不满足）会在 evidence_worker._normalize_batch
    里把 disqualified 写 true，下游 evidence_mapper 自动跳过 gap round。"""
    start = time.perf_counter()
    self_signals = query_plan.applicant_self_signals if query_plan else None
    cand_dir = output_dir / "step4_candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    # 双份落盘：fetched 是 fetcher 抓回的全集；sent 是 worker dedup+cap 后真正送 LLM 的子集
    visual_log_fetched_dir = output_dir / "step4_visual_log_fetched"
    visual_log_sent_dir = output_dir / "step4_visual_log_sent"
    visual_log_fetched_dir.mkdir(parents=True, exist_ok=True)
    visual_log_sent_dir.mkdir(parents=True, exist_ok=True)
    # 模块 3 round 1 用的 fetched_pages 全文池（避免被 LLM 裁成 snippet 后再次进 LLM）
    fetched_pages_dump_dir = output_dir / "step4_fetched_pages"
    evidence_results: list[CandidateEvidence] = []

    def _process(candidate):
        batch = map_evidence_for_batch(
            task_package=task_package,
            candidates=[candidate],
            batch_id=f"cand_{candidate.candidate_id}",
            self_signals=self_signals,
            model=model,
            reasoning_effort=reasoning_effort,
            visual_log_dir=visual_log_fetched_dir,
            visual_log_sent_dir=visual_log_sent_dir,
            fetched_pages_dump_dir=fetched_pages_dump_dir,
        )
        return candidate, batch

    def _load_or_run(candidate) -> CandidateEvidence | None:
        # 断点续传：cand file 已存在直接 load
        path = cand_dir / f"{candidate.candidate_id}.json"
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                # 只认带当前版本号的 wrapper；旧的扁平 CandidateEvidence dump（无
                # _cache_version）一律视为过期 → 落到下面重新计算，应用新白名单。
                if (
                    isinstance(raw, dict)
                    and raw.get("_cache_version") == _STEP4_CACHE_VERSION
                ):
                    cached = CandidateEvidence.model_validate(raw["evidence"])
                    logger.info(
                        "module2 step4 candidate=%s loaded_from_cache score=%.2f disqualified=%s",
                        candidate.candidate_id, cached.total_score, cached.disqualified,
                    )
                    return cached
                logger.info(
                    "module2 step4 candidate=%s cache stale (version mismatch), re-running",
                    candidate.candidate_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("module2 step4 cache invalid for %s, re-running: %s", candidate.candidate_id, exc)
        # 单候选错误隔离：LLM/网络炸了不拖死整 pipeline，写一条 disqualified 占位
        # ⚠️ 故意不把 fallback 写盘：transient 错误若 cache 下来，下次重跑会
        # `path.exists()` → 直接 load → 候选被永久排除。本次返回 fallback 让
        # 当前 run 能继续打榜，重跑时仍会真正调用 LLM。
        try:
            _, result = _process(candidate)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "module2 step4 candidate=%s FAILED, marking disqualified in-memory "
                "(NOT cached, will retry next run): %s",
                candidate.candidate_id, exc,
            )
            return CandidateEvidence(
                candidate=candidate,
                launch_date="",
                launch_date_evidence=[],
                disqualified=True,
                disqualification_reason=f"LLM/网络异常：{exc}",
                comparisons=[],
                total_score=0.0,
                searched_providers=[],
                searched_queries=[],
            )
        if not result.results:
            return None
        ev = result.results[0]
        _write_json(path, {"_cache_version": _STEP4_CACHE_VERSION, "evidence": ev.model_dump()})
        logger.info(
            "module2 step4 candidate=%s disqualified=%s score=%.2f",
            candidate.candidate_id, ev.disqualified, ev.total_score,
        )
        return ev

    worker_count = max(1, min(max_workers, len(shortlist.candidates)))
    if worker_count == 1:
        for candidate in shortlist.candidates:
            ev = _load_or_run(candidate)
            if ev is not None:
                evidence_results.append(ev)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(_load_or_run, c): c for c in shortlist.candidates}
            for future in as_completed(futures):
                ev = future.result()
                if ev is not None:
                    evidence_results.append(ev)
        order = {c.candidate_id: idx for idx, c in enumerate(shortlist.candidates)}
        evidence_results.sort(key=lambda e: order.get(e.candidate.candidate_id, 999))

    _write_json(
        output_dir / "step4_candidate_evidence.json",
        {
            "publication_no": task_package.patent.publication_no,
            "results": [item.model_dump() for item in evidence_results],
        },
    )
    qualified = sum(1 for e in evidence_results if not e.disqualified)
    logger.info(
        "module2 step4 publication=%s evaluated=%d qualified=%d disqualified=%d elapsed_ms=%d",
        task_package.patent.publication_no,
        len(evidence_results),
        qualified,
        len(evidence_results) - qualified,
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
