"""GPT-5.5 worker for module-two candidate filtering."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import ValidationError

from patentradar.core.constants import (
    CANDIDATE_FILTER_TARGET_CHARS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    PATENT_COUNTRY_CODES,
)
from patentradar.core.exceptions import LLMOutputError
from patentradar.llm.structured import generate_validated
from patentradar.llm.payload_compress import compress_payload_if_needed
from patentradar.schemas import CandidateShortlist, SearchResultsArtifact, TaskPackage


def filter_candidates(
    *,
    task_package: TaskPackage,
    search_results: SearchResultsArtifact,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> CandidateShortlist:
    user_text = _build_user_text(task_package=task_package, search_results=search_results)

    def _parse(payload: dict[str, Any]) -> CandidateShortlist:
        payload["publication_no"] = task_package.patent.publication_no
        _normalize_candidate_ids(payload)
        try:
            return CandidateShortlist.model_validate(payload)
        except ValidationError as exc:
            raise LLMOutputError(f"Invalid candidate shortlist JSON: {exc}\nPayload: {payload}") from exc

    return generate_validated(
        system=_load_prompt("candidate_extract.md"),
        user_text=user_text,
        parse=_parse,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
        response_format=_candidate_shortlist_response_format(),
        timeout=1200,
        attempts=3,
    )


def _normalize_candidate_ids(payload: dict[str, Any]) -> None:
    """Force candidate_id to be contiguous P01..P{N} regardless of LLM output.

    LLMs sometimes emit non-sequential ids (P14, P24, ..., P10-P21) which makes
    downstream batching and cross-step references ambiguous. We rewrite ids
    after the LLM call but before schema validation.
    """
    for index, candidate in enumerate(payload.get("candidates", []), start=1):
        candidate["candidate_id"] = f"P{index:02d}"


def _load_prompt(name: str) -> str:
    return resources.files("patentradar.llm.prompts").joinpath(name).read_text(encoding="utf-8")


def _build_user_text(*, task_package: TaskPackage, search_results: SearchResultsArtifact) -> str:
    # 入口处先做 top-N 截断 + snippet 截断：实测 GPT-5.5 codex API 在 prompt
    # 字符数 >100K 时容易生成不稳定（whitespace 死循环），所以这里主动控制：
    # - 保留 top-200（覆盖 ≈ top-250 的 88% 唯一域名，但 prompt 缩小 20%）
    # - snippet 截到 300 字（关键候选信息在前 200-250 字，剩下多是营销话术）
    # 之后再交给 compress_payload_if_needed 做兜底压缩。
    compact_results = [
        {
            "result_id": result.result_id,
            "query_id": result.query_id,
            "query": result.query,
            "provider": result.provider,
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet[:300],
            "published_date": result.published_date,
        }
        for result in search_results.results[:200]
    ]
    display_name, working_lang = PATENT_COUNTRY_CODES.get(
        task_package.patent.country_code,
        (task_package.patent.country_code or "Unknown", "en"),
    )
    payload = {
        "patent": {
            "publication_no": task_package.patent.publication_no,
            "title": task_package.patent.title,
            "applicants": task_package.patent.applicants,
            "application_date": task_package.patent.application_date,
        },
        "patent_country": {
            "code": task_package.patent.country_code,
            "display_name": display_name,
            "working_language": working_lang,
        },
        "technology_tag": task_package.technology_tag,
        "claim_1_text": task_package.claim_1_text,
        "claim_1_features": [
            {"feature_id": feature.feature_id, "feature_text": feature.feature_text}
            for feature in task_package.claim_1_features
        ],
        "search_results": compact_results,
    }
    # 兜底压缩：若入口截断后仍超 CANDIDATE_FILTER_TARGET_CHARS（默认 100K），
    # 由 payload_compress 继续逐档砍 snippet 长度 / search_results 条数
    compress_payload_if_needed(
        payload,
        target_chars=CANDIDATE_FILTER_TARGET_CHARS,
        context_label="candidate_worker",
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _candidate_shortlist_response_format() -> dict[str, Any]:
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
            "publication_no": {"type": "string"},
            "candidates": {"type": "array", "minItems": 8, "maxItems": 12, "items": candidate_schema},
        },
        "required": ["publication_no", "candidates"],
    }
    return {"type": "json_schema", "name": "candidate_shortlist", "strict": True, "schema": schema}
