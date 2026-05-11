"""GPT-5.5 worker for module-two candidate evidence mapping."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import ValidationError

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.core.exceptions import LLMOutputError
from patentradar.llm import codex
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
) -> EvidenceBatchResult:
    fetched_images_by_candidate = fetched_images_by_candidate or {}
    user_text = _build_user_text(
        task_package=task_package,
        candidates=candidates,
        search_results_by_candidate=search_results_by_candidate,
        fetched_pages_by_candidate=fetched_pages_by_candidate,
        fetched_images_by_candidate=fetched_images_by_candidate,
        is_gap_round=is_gap_round,
    )
    image_bytes_list = _flatten_images(candidates, fetched_images_by_candidate)
    payload = codex.chat_json(
        system=_load_prompt("evidence_extract.md"),
        user_text=user_text,
        images=image_bytes_list or None,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
        response_format=_evidence_batch_response_format(),
        timeout=1500,
        attempts=3,
    )
    payload["publication_no"] = task_package.patent.publication_no
    payload["batch_id"] = batch_id
    try:
        result = EvidenceBatchResult.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(f"Invalid evidence batch JSON: {exc}\nPayload: {payload}") from exc
    return _normalize_batch(result, task_package=task_package, candidates=candidates)


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
        for img in images[:6]:
            image_manifest.append({
                "global_index": image_cursor,
                "url": img.get("url", ""),
                "title": img.get("title", ""),
            })
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
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _flatten_images(
    candidates: list[Candidate],
    fetched_images_by_candidate: dict[str, list[dict]],
) -> list[bytes]:
    """Flatten per-candidate images into a single ordered list matching the
    `global_index` placed in user_text manifests. Caps each candidate at 6
    images to keep batch context manageable."""
    out: list[bytes] = []
    for candidate in candidates:
        for img in fetched_images_by_candidate.get(candidate.candidate_id, [])[:6]:
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
