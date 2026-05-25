"""GPT-5.5 worker for module-three full claim-chart completion.

Two rounds per candidate:
- Round 1: evaluate every feature, identify gaps, emit suggested_followup_queries
- Round 2: with additional evidence fetched, output finalized FullClaimChartCandidate

Per-candidate (not batched), because including all claims for 5 candidates would
push context near the GPT-5.5 limit. Single-candidate also keeps debugging simple.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Any

logger = logging.getLogger(__name__)

# 单候选 vision 图片上限：模块三 round 2 看 5 张。跟模块二对齐。
_VISION_IMAGES_PER_CANDIDATE = 5

from pydantic import ValidationError

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.core.exceptions import LLMOutputError
from pathlib import Path

from patentradar.fetcher.image_utils import dump_visual_log, png_hash
from patentradar.llm import get_llm_provider
from patentradar.llm.payload_compress import compress_payload_if_needed
from patentradar.schemas import (
    Candidate,
    CandidateEvidence,
    ClaimChartEntry,
    FeatureComparison,
    FullClaimChartCandidate,
    SearchResult,
    TaskPackage,
)


def evaluate_candidate(
    *,
    task_package: TaskPackage,
    candidate: Candidate,
    module_two_evidence: CandidateEvidence,
    evidence_pool_pages: list[dict[str, str]],
    evidence_pool_images: list[dict],
    new_search_results: list[SearchResult] | None = None,
    is_finalization_round: bool,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    visual_log_sent_dir: Path | None = None,
    visual_log_candidate_id: str | None = None,
) -> FullClaimChartCandidate:
    """Run one LLM round (initial or finalization)."""
    evidence_pool_images = _dedupe_images(evidence_pool_images)[:_VISION_IMAGES_PER_CANDIDATE]
    # dedup + cap 后即 LLM 实际看到的图：仅 round 2 (finalization) 落盘 sent 子集
    if (
        is_finalization_round
        and visual_log_sent_dir is not None
        and visual_log_candidate_id is not None
    ):
        dump_visual_log(visual_log_sent_dir, visual_log_candidate_id, evidence_pool_images)
    image_bytes_list = [img["png"] for img in evidence_pool_images if isinstance(img.get("png"), (bytes, bytearray))]
    provider = get_llm_provider()
    images_arg = image_bytes_list or None
    if images_arg and not provider.supports_vision:
        logger.warning(
            "full_claim_chart_worker: dropping %d image(s) — provider %s lacks vision; "
            "judging from text-only evidence.",
            len(images_arg), provider.name,
        )
        images_arg = None
    payload = provider.chat_json(
        system=_load_prompt(),
        user_text=_build_user_text(
            task_package=task_package,
            candidate=candidate,
            module_two_evidence=module_two_evidence,
            evidence_pool_pages=evidence_pool_pages,
            evidence_pool_images=evidence_pool_images,
            new_search_results=new_search_results or [],
            is_finalization_round=is_finalization_round,
        ),
        images=images_arg,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
        response_format=_full_claim_chart_response_format(),
        timeout=1500,
        attempts=3,
    )
    payload = _backfill_from_inputs(payload, task_package, candidate, module_two_evidence)
    _drop_empty_url_evidence(payload)
    try:
        return FullClaimChartCandidate.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(f"Invalid full claim chart JSON: {exc}\nPayload: {payload}") from exc


def _dedupe_images(images: list[dict]) -> list[dict]:
    """按 PNG 内容哈希去重 + 按启发式 score 全局降序排序。

    保证后续 [:N] 切割时高 score 图（PDF 关键页 / HTML 强信号）优先入选。
    稳定排序：相同 score 保留 fetch 顺序。
    """
    seen: set[str] = set()
    out: list[dict] = []
    for img in images:
        png = img.get("png")
        if not isinstance(png, (bytes, bytearray)):
            continue
        h = png_hash(bytes(png))
        if h in seen:
            continue
        seen.add(h)
        out.append(img)
    out.sort(key=lambda x: x.get("score", 0), reverse=True)
    return out


def _drop_empty_url_evidence(payload: dict[str, Any]) -> None:
    """同 evidence_worker._drop_empty_url_evidence：DeepSeek 偶尔会塞 url='' 的
    evidence，绕过这道防御 Pydantic 校验会让整轮失败。模块三 payload 形态嵌套更深，
    所有可能放 EvidenceSource 的字段都得 sanitize。

    清空后若 comparison.evidence 列表已空 → 同步把 status 降级为「证据不足」，
    避免"status=明确满足 但 evidence=[]"对外报告（人工审核找不到依据）。
    """
    def _scrub(items: list | None) -> list:
        if not items:
            return []
        return [i for i in items if isinstance(i.get("url"), str) and i["url"].strip()]

    # ⚠️ 字段名必须是 claim_charts（复数），与 schema 一致；旧版误写 claim_chart 单数，
    # 让这段 scrub 永远空跑 → 空 URL 透传到 Pydantic 触发 ValidationError 让整轮失败。
    for entry in payload.get("claim_charts") or []:
        for comparison in entry.get("comparisons") or []:
            before = len(comparison.get("evidence") or [])
            scrubbed = _scrub(comparison.get("evidence"))
            comparison["evidence"] = scrubbed
            if before > 0 and not scrubbed:
                # 同 evidence_worker：只改 status，score 由 Pydantic 重写。
                comparison["status"] = "证据不足"
                reason = comparison.get("reasoning") or ""
                marker = "（LLM 给出的 evidence URL 为空，按证据不足处理）"
                if marker not in reason:
                    comparison["reasoning"] = (reason + " " + marker).strip()
    payload["launch_date_evidence"] = _scrub(payload.get("launch_date_evidence"))


def _load_prompt() -> str:
    return resources.files("patentradar.llm.prompts").joinpath("full_claim_chart.md").read_text(
        encoding="utf-8"
    )


def _build_user_text(
    *,
    task_package: TaskPackage,
    candidate: Candidate,
    module_two_evidence: CandidateEvidence,
    evidence_pool_pages: list[dict[str, str]],
    evidence_pool_images: list[dict],
    new_search_results: list[SearchResult],
    is_finalization_round: bool,
) -> str:
    # surrounding_text 是图所在 HTML 上下文（figcaption + 前后段落首句拼接），
    # 让 LLM 看图时能做"图-文交叉验证"。详见 evidence_worker._build_user_text 同字段注释。
    images_manifest = [
        {
            "global_index": idx,
            "url": img.get("url", ""),
            "title": img.get("title", ""),
            "surrounding_text": (img.get("surrounding_text") or "")[:300],
        }
        for idx, img in enumerate(evidence_pool_images)
    ]
    all_claims = [
        {
            "claim_no": claim.claim_no,
            "claim_text": claim.claim_text,
            "features": [
                {"feature_id": feature.feature_id, "feature_text": feature.feature_text}
                for feature in claim.features
            ],
        }
        for claim in task_package.claims
    ]
    payload = {
        "is_finalization_round": is_finalization_round,
        "patent": {
            "publication_no": task_package.patent.publication_no,
            "title": task_package.patent.title,
            "applicants": task_package.patent.applicants,
            "application_date": task_package.patent.application_date,
        },
        "claim_1_text": task_package.claim_1_text,
        "all_claims": all_claims,
        "module_two_evidence": {
            "launch_date": module_two_evidence.launch_date,
            "launch_date_evidence": [e.model_dump() for e in module_two_evidence.launch_date_evidence],
            "disqualified": module_two_evidence.disqualified,
            "disqualification_reason": module_two_evidence.disqualification_reason,
            # Queries module two already tried — module three should NOT repeat
            # these literally; pick different phrasing / angle / language.
            "queries_already_tried_in_module_two": list(module_two_evidence.searched_queries),
            "comparisons_for_claim_1": [c.model_dump() for c in module_two_evidence.comparisons],
            "evidence_pool": [
                {
                    "url": page["url"],
                    "title": page.get("title", ""),
                    "text": (page.get("text") or "")[:4000],
                }
                for page in evidence_pool_pages[:20]
            ],
            "images_manifest": images_manifest,
        },
        "candidate": candidate.model_dump(),
        "new_search_results": [
            {
                "result_id": r.result_id,
                "provider": r.provider,
                "title": r.title,
                "url": r.url,
                "snippet": (r.snippet or "")[:600],
                "query": r.query,
                "published_date": r.published_date,
            }
            for r in new_search_results[:40]
        ],
    }
    # 超阈值时自动压缩 evidence_pool.text 长度 / new_search_results.snippet / 数量
    compress_payload_if_needed(
        payload,
        context_label=f"full_claim_chart_worker finalization={is_finalization_round}",
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _backfill_from_inputs(
    payload: dict[str, Any],
    task_package: TaskPackage,
    candidate: Candidate,
    module_two_evidence: CandidateEvidence,
) -> dict[str, Any]:
    """Fill in fields LLM may have left blank or wrong, and enforce per-feature
    `patent_feature` text to match task_package authoritative source."""
    payload.setdefault("candidate", candidate.model_dump())
    # Restore canonical candidate fields in case LLM altered them.
    payload["candidate"] = candidate.model_dump()
    payload.setdefault("launch_date", module_two_evidence.launch_date)
    payload.setdefault("launch_date_evidence", [e.model_dump() for e in module_two_evidence.launch_date_evidence])
    payload.setdefault("disqualified", module_two_evidence.disqualified)
    payload.setdefault(
        "disqualification_reason", module_two_evidence.disqualification_reason
    )
    # Enforce feature_id pattern + patent_feature text from task_package.
    feature_text_by_id = {
        feature.feature_id: feature.feature_text
        for claim in task_package.claims
        for feature in claim.features
    }
    for claim_entry in payload.get("claim_charts", []):
        for comparison in claim_entry.get("comparisons", []):
            fid = comparison.get("feature_id")
            if fid in feature_text_by_id:
                comparison["patent_feature"] = feature_text_by_id[fid]
    return payload


def _full_claim_chart_response_format() -> dict[str, Any]:
    evidence_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "url": {"type": "string"},
            "title": {"type": "string"},
            "source_name": {"type": "string"},
            "snippet": {"type": "string"},
        },
        "required": ["url", "title", "source_name", "snippet"],
    }
    comparison_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "feature_id": {"type": "string", "pattern": "^C\\d+-F\\d+$"},
            "patent_feature": {"type": "string"},
            "competitor_feature": {"type": "string"},
            "status": {"type": "string", "enum": ["明确满足", "可能满足", "证据不足", "明确不满足"]},
            "score": {"type": "number"},
            "evidence": {"type": "array", "items": evidence_schema},
            "reasoning": {"type": "string"},
            "suggested_followup_queries": {"type": "array", "items": {"type": "string"}},
            "evidence_gap_brief": {"type": "string"},
        },
        "required": [
            "feature_id",
            "patent_feature",
            "competitor_feature",
            "status",
            "score",
            "evidence",
            "reasoning",
            "suggested_followup_queries",
            "evidence_gap_brief",
        ],
    }
    claim_entry_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_no": {"type": "integer"},
            "claim_text": {"type": "string"},
            "comparisons": {"type": "array", "items": comparison_schema},
            "claim_score": {"type": "number"},
        },
        "required": ["claim_no", "claim_text", "comparisons", "claim_score"],
    }
    candidate_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate_id": {"type": "string", "pattern": "^P\\d{2}$"},
            "company": {"type": "string"},
            "company_en": {"type": "string"},
            "product_name": {"type": "string"},
            "product_name_en": {"type": "string"},
            "product_version": {"type": "string"},
            "market": {"type": "string"},
            "reason_for_deep_dive": {"type": "string"},
            "source_result_ids": {"type": "array", "items": {"type": "string"}},
            "source_urls": {"type": "array", "items": {"type": "string"}},
            "initial_evidence_summary": {"type": "string"},
        },
        "required": [
            "candidate_id",
            "company",
            "company_en",
            "product_name",
            "product_name_en",
            "product_version",
            "market",
            "reason_for_deep_dive",
            "source_result_ids",
            "source_urls",
            "initial_evidence_summary",
        ],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate": candidate_schema,
            "launch_date": {"type": "string"},
            "launch_date_evidence": {"type": "array", "items": evidence_schema},
            "disqualified": {"type": "boolean"},
            "disqualification_reason": {"type": "string"},
            "claim_charts": {"type": "array", "items": claim_entry_schema},
            "claim_1_score": {"type": "number"},
            "total_score": {"type": "number"},
            "searched_queries": {"type": "array", "items": {"type": "string"}},
            "searched_providers": {
                "type": "array",
                "items": {"type": "string", "enum": ["tavily", "bocha", "exa", "brave"]},
            },
        },
        "required": [
            "candidate",
            "launch_date",
            "launch_date_evidence",
            "disqualified",
            "disqualification_reason",
            "claim_charts",
            "claim_1_score",
            "total_score",
            "searched_queries",
            "searched_providers",
        ],
    }
    return {"type": "json_schema", "name": "full_claim_chart_candidate", "strict": True, "schema": schema}
