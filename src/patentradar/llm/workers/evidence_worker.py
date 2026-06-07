"""GPT-5.5 worker for module-two candidate evidence mapping."""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Any

from pydantic import ValidationError

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.core.exceptions import LLMOutputError
from patentradar.core.launch_date import launch_before_application
from pathlib import Path

from patentradar.fetcher.image_utils import dump_visual_log, png_hash
from patentradar.llm import get_llm_provider
from patentradar.llm.payload_compress import compress_payload_if_needed
from patentradar.schemas import (
    Candidate,
    CandidateEvidence,
    ClaimFeature,
    EvidenceBatchResult,
    FeatureComparison,
    SearchResult,
    TaskPackage,
)
from patentradar.search.relevance import rank_pages_by_relevance, rank_search_results
from patentradar.search.result_normalizer import canonical_url

logger = logging.getLogger(__name__)

# 单候选 vision 图片上限：模块二 round 2 看 5 张，配合 fetcher 端 top-K=1/page
# 和 alt-去重，让 LLM 看到的图集中在每个候选最高质量的 5 张。
_VISION_IMAGES_PER_CANDIDATE = 5


def judge_candidate_batch(
    *,
    task_package: TaskPackage,
    candidates: list[Candidate],
    search_results_by_candidate: dict[str, list[SearchResult]],
    fetched_pages_by_candidate: dict[str, list[dict[str, str]]],
    fetched_images_by_candidate: dict[str, list[dict]] | None = None,
    batch_id: str,
    is_gap_round: bool = False,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    visual_log_sent_dir: Path | None = None,
) -> EvidenceBatchResult:
    fetched_images_by_candidate = _dedupe_images_per_candidate(fetched_images_by_candidate or {})
    provider = get_llm_provider()
    # vision 不可用时同步清空 image manifest：否则 user_text 里仍带 image_manifest
    # 引用（global_index/url/surrounding_text），LLM 看到引用却收不到图，可能
    # 凭引用编造证据。此时应让 LLM 完全不知道图存在。
    if fetched_images_by_candidate and not provider.supports_vision:
        logger.warning(
            "evidence_worker: provider %s does not support vision; dropping "
            "image manifest from prompt so LLM judges from text-only evidence.",
            provider.name,
        )
        fetched_images_by_candidate = {}
    # dedup + score 排序 + [:cap] 后即 LLM 实际送入图集合：落盘到 sent_dir
    if visual_log_sent_dir is not None and is_gap_round:
        # 仅 round 2 (is_gap_round=True) 才真发图给 LLM；round 1 text-only 不 dump
        for cid, imgs in fetched_images_by_candidate.items():
            dump_visual_log(visual_log_sent_dir, cid, imgs[:_VISION_IMAGES_PER_CANDIDATE])
    user_text = _build_user_text(
        task_package=task_package,
        candidates=candidates,
        search_results_by_candidate=search_results_by_candidate,
        fetched_pages_by_candidate=fetched_pages_by_candidate,
        fetched_images_by_candidate=fetched_images_by_candidate,
        is_gap_round=is_gap_round,
    )
    image_bytes_list = _flatten_images(candidates, fetched_images_by_candidate)
    images_arg = image_bytes_list or None
    payload = provider.chat_json(
        system=_load_prompt("evidence_extract.md"),
        user_text=user_text,
        images=images_arg,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
        response_format=_evidence_batch_response_format(),
        timeout=1500,
        attempts=3,
    )
    payload["publication_no"] = task_package.patent.publication_no
    payload["batch_id"] = batch_id
    _drop_empty_url_evidence(
        payload,
        allowed_urls_by_candidate=_allowed_urls_by_candidate(
            candidates=candidates,
            search_results_by_candidate=search_results_by_candidate,
            fetched_pages_by_candidate=fetched_pages_by_candidate,
            fetched_images_by_candidate=fetched_images_by_candidate,
        ),
    )
    try:
        result = EvidenceBatchResult.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(f"Invalid evidence batch JSON: {exc}\nPayload: {payload}") from exc
    return _normalize_batch(result, task_package=task_package, candidates=candidates)


def _allowed_urls_by_candidate(
    *,
    candidates: list[Candidate],
    search_results_by_candidate: dict[str, list[SearchResult]],
    fetched_pages_by_candidate: dict[str, list[dict[str, str]]],
    fetched_images_by_candidate: dict[str, list[dict]] | None,
) -> dict[str, set[str]]:
    """逐候选收集 LLM 实际见过的 URL（canonical 化）作为合法 evidence 白名单。
    引用任何不在其中的 URL = 编造。"""
    fetched_images_by_candidate = fetched_images_by_candidate or {}
    allowed: dict[str, set[str]] = {}
    for candidate in candidates:
        cid = candidate.candidate_id
        urls: set[str] = set()
        for r in search_results_by_candidate.get(cid, []):
            if r.url:
                urls.add(canonical_url(r.url))
        for page in fetched_pages_by_candidate.get(cid, []):
            if page.get("url"):
                urls.add(canonical_url(page["url"]))
        for img in fetched_images_by_candidate.get(cid, []):
            if img.get("url"):
                urls.add(canonical_url(img["url"]))
        for src in candidate.source_urls:
            if src:
                urls.add(canonical_url(src))
        allowed[cid] = urls
    return allowed


def _drop_empty_url_evidence(
    payload: dict[str, Any],
    *,
    allowed_urls_by_candidate: dict[str, set[str]] | None = None,
) -> None:
    """LLM 偶尔给某条 feature 配上 url='' 的 evidence 凑数；Pydantic 的
    `url must be absolute` 会让整个 batch 抛 ValidationError，拖垮 step4。
    这里就地剔除所有 url 为空字符串/None/空白的 evidence 项（含 launch_date_evidence）。

    allowed_urls_by_candidate 非 None 时，额外剔除 canonical 后不在该候选抓取池里的
    evidence——语法合法但从未抓取过的 URL 也算编造，不该作为可复核证据。

    清空后若 comparison.evidence 列表已空 → 同步把 status 降级为「证据不足」、
    score 降到 0.3，并在 reasoning 末尾追加说明。否则会出现「status=明确满足
    但 evidence=[]」的对外报告，让人工审核找不到任何依据。
    """
    def _scrub(items: list | None, allowed: set[str] | None) -> list:
        if not items:
            return []
        kept = []
        for i in items:
            url = i.get("url")
            if not (isinstance(url, str) and url.strip()):
                continue
            if allowed is not None and canonical_url(url) not in allowed:
                continue
            kept.append(i)
        return kept

    for result in payload.get("results") or []:
        cid = (result.get("candidate") or {}).get("candidate_id")
        allowed = (
            allowed_urls_by_candidate.get(cid)
            if allowed_urls_by_candidate is not None
            else None
        )
        for comparison in result.get("comparisons") or []:
            before = len(comparison.get("evidence") or [])
            scrubbed = _scrub(comparison.get("evidence"), allowed)
            comparison["evidence"] = scrubbed
            if before > 0 and not scrubbed:
                # 原来有 evidence 但全被剔除（空 URL 或不在抓取池）→ 失去依据，降级
                # status；score 不在此处赋值——Pydantic 的 FeatureComparison.validate_score
                # 会按 status 强制重写（"证据不足" → 0.3），手动赋值是 dead code。
                comparison["status"] = "证据不足"
                reason = comparison.get("reasoning") or ""
                marker = "（LLM 给出的 evidence URL 为空或不在抓取池内，按证据不足处理）"
                if marker not in reason:
                    comparison["reasoning"] = (reason + " " + marker).strip()
        result["launch_date_evidence"] = _scrub(result.get("launch_date_evidence"), allowed)
        # 失格不在此处裁定——交给 _normalize_batch 用代码判定（不信任 LLM 的
        # disqualified）。这里只负责把编造/空 URL 清掉。


def _load_prompt(name: str) -> str:
    return resources.files("patentradar.llm.prompts").joinpath(name).read_text(encoding="utf-8")


def _build_user_text(
    *,
    task_package: TaskPackage,
    candidates: list[Candidate],
    search_results_by_candidate: dict[str, list[SearchResult]],
    fetched_pages_by_candidate: dict[str, list[dict[str, str]]],
    fetched_images_by_candidate: dict[str, list[dict]] | None = None,
    is_gap_round: bool = False,
) -> str:
    fetched_images_by_candidate = fetched_images_by_candidate or {}
    image_cursor = 0
    candidate_payloads = []
    for candidate in candidates:
        search_results = search_results_by_candidate.get(candidate.candidate_id, [])
        pages = fetched_pages_by_candidate.get(candidate.candidate_id, [])
        images = fetched_images_by_candidate.get(candidate.candidate_id, [])
        keywords = _candidate_keywords(candidate, task_package.claim_1_features)
        # Rank by relevance to candidate + claim-1 features, then truncate.
        # 30/10/4000 leaves more token budget for LLM reasoning vs the old
        # 70/20/6000 cap that pushed the batch close to context limit.
        ranked_results = rank_search_results(search_results, keywords=keywords)
        ranked_pages = rank_pages_by_relevance(pages, keywords=keywords)
        # Build image manifest entries so LLM knows which input_image belongs
        # to which candidate (the image bytes themselves are passed alongside
        # via codex.chat_json(images=...) in batch order).
        image_manifest = []
        for img in images[:_VISION_IMAGES_PER_CANDIDATE]:
            entry = {
                "global_index": image_cursor,
                "url": img.get("url", ""),
                "title": img.get("title", ""),
            }
            # surrounding_text 是图所在 HTML 上下文（figcaption + 前后段落首句拼接），
            # 让 LLM 看图时能做"图-文交叉验证"：很多 HTML 的 <img alt> 为空，但
            # surrounding_text 写明"图 3：自定义车位界面"——这种是判图的关键文字信号。
            # 字段为空字符串时 LLM 端按"无上下文"处理。
            entry["surrounding_text"] = (img.get("surrounding_text") or "")[:300]
            image_manifest.append(entry)
            image_cursor += 1
        candidate_payloads.append(
            {
                "candidate": candidate.model_dump(),
                "search_results": [
                    {
                        "result_id": item.result_id,
                        "provider": item.provider,
                        "title": item.title,
                        "url": item.url,
                        "snippet": (item.snippet or "")[:600],
                        "query": item.query,
                        "published_date": item.published_date,
                    }
                    for item in ranked_results[:30]
                ],
                "fetched_pages": [
                    {
                        "url": page["url"],
                        "title": page.get("title", ""),
                        "text": (page.get("text") or "")[:4000],
                    }
                    for page in ranked_pages[:10]
                ],
                "fetched_page_images": image_manifest,
            }
        )
    payload = {
        # Round flag: round 1 expects suggested_followup_queries to be filled
        # for gap features; round 2 (gap evidence already added) expects them
        # to be empty arrays.
        "is_gap_round": is_gap_round,
        "patent": {
            "publication_no": task_package.patent.publication_no,
            "title": task_package.patent.title,
            "applicants": task_package.patent.applicants,
            "application_date": task_package.patent.application_date,
        },
        # Claim 1 full original text gives LLM the holistic protection scope
        # that per-feature snippets alone may miss (cross-feature references,
        # boundary semantics, "其特征在于" framing).
        "claim_1_text": task_package.claim_1_text,
        "claim_1_features": [
            {"feature_id": feature.feature_id, "feature_text": feature.feature_text}
            for feature in task_package.claim_1_features
        ],
        "candidates": candidate_payloads,
    }
    # 超阈值时自动压缩低优先级字段（fetched_pages.text 长度、search snippet 等）
    compress_payload_if_needed(
        payload,
        context_label=f"evidence_worker is_gap_round={is_gap_round}",
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _dedupe_images_per_candidate(
    by_candidate: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """按 PNG 内容哈希在单个候选内去重 + 按启发式 score 全局降序排序。

    排序保证 worker 端 [:N] 切割时优先保留高分图（含 PDF 关键页 + HTML 高
    score 命中），而不是按 fetch 批次顺序。
    """
    out: dict[str, list[dict]] = {}
    for cid, imgs in by_candidate.items():
        seen: set[str] = set()
        deduped: list[dict] = []
        for img in imgs:
            png = img.get("png")
            if not isinstance(png, (bytes, bytearray)):
                continue
            h = png_hash(bytes(png))
            if h in seen:
                continue
            seen.add(h)
            deduped.append(img)
        # 稳定排序：相同 score 保留原（fetch 批次）顺序——即 gap 图仍在前
        deduped.sort(key=lambda x: x.get("score", 0), reverse=True)
        out[cid] = deduped
    return out


def _flatten_images(
    candidates: list[Candidate],
    fetched_images_by_candidate: dict[str, list[dict]],
) -> list[bytes]:
    """Flatten per-candidate images into a single ordered list matching the
    `global_index` placed in user_text manifests. Capped per-candidate to
    keep batch context manageable (see _VISION_IMAGES_PER_CANDIDATE)."""
    out: list[bytes] = []
    for candidate in candidates:
        for img in fetched_images_by_candidate.get(candidate.candidate_id, [])[:_VISION_IMAGES_PER_CANDIDATE]:
            png = img.get("png")
            if isinstance(png, (bytes, bytearray)):
                out.append(bytes(png))
    return out


def _candidate_keywords(candidate: Candidate, claim_features: list[ClaimFeature]) -> list[str]:
    """Keywords used to rank evidence relevance for one candidate. Includes
    candidate identity terms + the head of each claim-1 feature so pages with
    sizes / capacities / connection words bubble up."""
    terms: list[str] = []
    for piece in (candidate.company, candidate.product_name, candidate.product_version):
        if piece and piece.strip():
            terms.append(piece.strip())
    for feature in claim_features:
        text = feature.feature_text or ""
        if text:
            terms.append(text[:32])
    return terms


def _normalize_batch(
    result: EvidenceBatchResult,
    *,
    task_package: TaskPackage,
    candidates: list[Candidate],
) -> EvidenceBatchResult:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    feature_by_id = {feature.feature_id: feature.feature_text for feature in task_package.claim_1_features}
    normalized: list[CandidateEvidence] = []
    for item in result.results:
        if item.candidate.candidate_id in candidate_by_id:
            item.candidate = candidate_by_id[item.candidate.candidate_id]
        comparison_by_id = {comparison.feature_id: comparison for comparison in item.comparisons}
        comparisons = []
        for feature_id, feature_text in feature_by_id.items():
            comparison = comparison_by_id.get(feature_id)
            if comparison is None:
                comparison = _missing_comparison(feature_id, feature_text)
            comparison.patent_feature = feature_text
            comparisons.append(comparison)
        item.comparisons = comparisons
        # 失格完全由代码裁定，**不信任 LLM 的 disqualified**（它可能凭空标 True，
        # 或给一个晚于申请日的 launch_date 仍标失格）。合法依据只有两条：
        #   1) 某权1特征「明确不满足」——此处 status 已是终值（无证据的负向已被
        #      FeatureComparison.validate_score 降级为证据不足），故只剩有证据支撑的；
        #   2) 上市日期可考证地早于专利申请日——需有 launch_date_evidence（编造/空
        #      URL 已被 _drop_empty_url_evidence 清掉）且年份能解析并确实更早。
        unsatisfied = [c.feature_id for c in comparisons if c.status == "明确不满足"]
        launch_before = bool(item.launch_date_evidence) and launch_before_application(
            item.launch_date, task_package.patent.application_date
        )
        if unsatisfied:
            item.disqualified = True
            item.disqualification_reason = (
                f"权 1 特征 {', '.join(unsatisfied)} 明确不满足，按全覆盖原则无侵权可能"
            )
        elif launch_before:
            item.disqualified = True
            item.disqualification_reason = (
                f"公开上市日期（{item.launch_date}）早于专利申请日"
                f"（{task_package.patent.application_date}）"
            )
        else:
            item.disqualified = False
            item.disqualification_reason = ""
        item = CandidateEvidence.model_validate(item.model_dump())
        normalized.append(item)
    result.results = normalized
    return result


def _missing_comparison(feature_id: str, feature_text: str) -> FeatureComparison:
    return FeatureComparison(
        feature_id=feature_id,
        patent_feature=feature_text,
        competitor_feature="",
        status="证据不足",
        score=0.3,
        evidence=[],
        reasoning="模型输出缺少该技术特征的判断，按证据不足处理。",
    )


def _evidence_batch_response_format() -> dict[str, Any]:
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
            "feature_id": {"type": "string", "pattern": "^C1-F\\d+$"},
            "patent_feature": {"type": "string"},
            "competitor_feature": {"type": "string"},
            "status": {"type": "string", "enum": ["明确满足", "可能满足", "证据不足", "明确不满足"]},
            "score": {"type": "number"},
            "evidence": {"type": "array", "items": evidence_schema},
            "reasoning": {"type": "string"},
            "suggested_followup_queries": {"type": "array", "items": {"type": "string"}},
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
        ],
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
    candidate_evidence_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate": candidate_schema,
            "launch_date": {"type": "string"},
            "launch_date_evidence": {"type": "array", "items": evidence_schema},
            "disqualified": {"type": "boolean"},
            "disqualification_reason": {"type": "string"},
            "comparisons": {"type": "array", "items": comparison_schema},
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
            "comparisons",
            "total_score",
            "searched_queries",
            "searched_providers",
        ],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "publication_no": {"type": "string"},
            "batch_id": {"type": "string"},
            "results": {"type": "array", "items": candidate_evidence_schema},
        },
        "required": ["publication_no", "batch_id", "results"],
    }
    return {"type": "json_schema", "name": "evidence_batch", "strict": True, "schema": schema}
