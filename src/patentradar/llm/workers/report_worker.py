"""模块四 worker：把单次大 LLM 调用拆成 1 次 overview + N 次 per-candidate 调用。

为什么要拆：codex SSE 后端单次响应有约 15 分钟硬上限，6 候选 × 12 claim 的整份
markdown 一次跑总会断流（实测 reasoning=high/medium、verbosity=medium 都救不回）。
拆成多次小调用每次都在 5 分钟内完成，稳定。

输出仍是单份 markdown，由代码拼接而成。
"""

from __future__ import annotations

import json
import logging
from importlib import resources

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.llm import get_llm_provider
from patentradar.schemas import (
    FullClaimChartCandidate,
    FullClaimChartReport,
    SimilarPatentSearchHint,
    TaskPackage,
)

logger = logging.getLogger(__name__)


def generate_report_markdown(
    *,
    task_package: TaskPackage,
    full_claim_chart_report: FullClaimChartReport,
    similar_patents_hint: SimilarPatentSearchHint | None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> str:
    provider = get_llm_provider()
    max_total_score = (
        max((c.total_score for c in full_claim_chart_report.top_competitors), default=0.0)
    )
    threshold = similar_patents_hint.threshold if similar_patents_hint else 80.0
    infringement_risk_triggered = max_total_score >= threshold

    # Pass 1: overview = 第 1 章节（专利信息）+ 第 2 章节（全文总结）
    logger.info("module4 generating overview (sections 1 + 2)")
    overview_md = provider.chat_text(
        system=_load_overview_prompt(),
        user_text=_build_overview_user_text(
            task_package=task_package,
            full_claim_chart_report=full_claim_chart_report,
            max_total_score=max_total_score,
            threshold=threshold,
            infringement_risk_triggered=infringement_risk_triggered,
        ),
        model=model,
        reasoning_effort="medium",
        verbosity="medium",
        timeout=900,
    )
    overview_md = _strip_markdown_fence(overview_md)

    # Pass 2..N+1: 每个 TOP candidate 单独生成对比子节
    candidate_blocks: list[str] = []
    for rank, candidate in enumerate(full_claim_chart_report.top_competitors, start=1):
        logger.info(
            "module4 generating TOP%d block: %s / %s",
            rank, candidate.candidate.company, candidate.candidate.product_name,
        )
        block = provider.chat_text(
            system=_load_candidate_prompt(),
            user_text=_build_candidate_user_text(
                task_package=task_package,
                candidate=candidate,
                rank=rank,
                total_top=len(full_claim_chart_report.top_competitors),
            ),
            model=model,
            reasoning_effort="medium",
            verbosity="medium",
            timeout=900,
        )
        candidate_blocks.append(_strip_markdown_fence(block))

    # 拼接：overview + TOP-N section header + candidate blocks + similar patents tail
    parts: list[str] = [overview_md]
    n = len(full_claim_chart_report.top_competitors)
    if n > 0:
        parts.append(f"## 3. TOP{n} 竞品深度对比\n")
        parts.extend(candidate_blocks)

    if infringement_risk_triggered and similar_patents_hint is not None:
        parts.append(_render_similar_patents_section(similar_patents_hint, threshold))

    return "\n\n".join(part.rstrip() for part in parts) + "\n"


def _load_overview_prompt() -> str:
    return resources.files("patentradar.llm.prompts").joinpath("report_overview.md").read_text(
        encoding="utf-8"
    )


def _load_candidate_prompt() -> str:
    return resources.files("patentradar.llm.prompts").joinpath("report_candidate.md").read_text(
        encoding="utf-8"
    )


def _build_overview_user_text(
    *,
    task_package: TaskPackage,
    full_claim_chart_report: FullClaimChartReport,
    max_total_score: float,
    threshold: float,
    infringement_risk_triggered: bool,
) -> str:
    # overview 用：每个 candidate 只取元信息 + 权 1 子集（不含非权 1 详情），
    # 让 LLM 能写最高分竞品的权 1 满足情况和缺口分析。
    top_summary = [_summarize_candidate_for_overview(c) for c in full_claim_chart_report.top_competitors]
    excluded_summary = [
        {
            "candidate_id": c.candidate.candidate_id,
            "company": c.candidate.company,
            "product_name": c.candidate.product_name,
            "disqualification_reason": c.disqualification_reason,
        }
        for c in full_claim_chart_report.excluded_candidates
    ]
    payload = {
        "patent": {
            "publication_no": task_package.patent.publication_no,
            "title": task_package.patent.title,
            "applicants": task_package.patent.applicants,
            "inventors": task_package.patent.inventors,
            "application_date": task_package.patent.application_date,
            "google_patents_url": task_package.patent.google_patents_url,
            "pdf_url": task_package.patent.pdf_url,
            "technology_tag": task_package.technology_tag,
            "all_claims_count": len(task_package.claims),
        },
        "top_competitors_summary": top_summary,
        "excluded_candidates_summary": excluded_summary,
        "max_total_score": max_total_score,
        "infringement_risk_threshold": threshold,
        "infringement_risk_triggered": infringement_risk_triggered,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _summarize_candidate_for_overview(candidate: FullClaimChartCandidate) -> dict:
    """overview 用的候选摘要：元信息 + 权 1 各 feature 的状态 + evidence_gap_brief。"""
    claim_1 = next((entry for entry in candidate.claim_charts if entry.claim_no == 1), None)
    claim_1_features = []
    if claim_1:
        for cmp in claim_1.comparisons:
            claim_1_features.append({
                "feature_id": cmp.feature_id,
                "patent_feature": cmp.patent_feature,
                "status": cmp.status,
                "evidence_gap_brief": cmp.evidence_gap_brief,
            })
    return {
        "candidate_id": candidate.candidate.candidate_id,
        "company": candidate.candidate.company,
        "product_name": candidate.candidate.product_name,
        "product_version": candidate.candidate.product_version,
        "launch_date": candidate.launch_date,
        "total_score": candidate.total_score,
        "claim_1_features": claim_1_features,
    }


def _build_candidate_user_text(
    *,
    task_package: TaskPackage,
    candidate: FullClaimChartCandidate,
    rank: int,
    total_top: int,
) -> str:
    payload = {
        "rank": rank,
        "total_top": total_top,
        "patent_publication_no": task_package.patent.publication_no,
        "all_claims_text": [
            {"claim_no": c.claim_no, "claim_text": c.claim_text}
            for c in task_package.claims
        ],
        "candidate_full": candidate.model_dump(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_similar_patents_section(
    hint: SimilarPatentSearchHint, threshold: float
) -> str:
    """静态渲染相似专利章节，不走 LLM（数据全是结构化的，模板化即可）。"""
    return (
        f"## 4. 相似专利人工核查\n\n"
        f"本专利已发现 ≥ {threshold:.0f} 分竞品，存在被侵权风险。基于公司专利池的布局，"
        f"本专利的同族延续案/分案极可能面临同样侵权风险，建议人工通过下方 "
        f"Google Patents 高级检索链接核查（链接已按国家代码 / 申请人 / 标题预先过滤），"
        f"也可在大为专利中检索同名专利。\n\n"
        f"| 项 | 值 |\n"
        f"|---|---|\n"
        f"| 国家代码 | {hint.country_code} |\n"
        f"| 申请人 | {hint.applicant} |\n"
        f"| 标题 | {hint.title} |\n"
        f"| 触发分数 | {hint.triggered_by_total_score:.2f}（阈值 {threshold:.0f}）|\n\n"
        f"[在 Google Patents 高级检索中打开]({hint.google_patents_search_url})\n"
    )


def _strip_markdown_fence(text: str) -> str:
    """LLM sometimes wraps the whole response in ```markdown ... ```. Strip."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
