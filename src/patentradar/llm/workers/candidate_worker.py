"""GPT-5.5 worker for module-two candidate filtering."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import ValidationError

from patentradar.core.constants import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    PATENT_COUNTRY_CODES,
)
from patentradar.core.exceptions import LLMOutputError
from patentradar.llm import get_llm_provider
from patentradar.schemas import CandidateShortlist, SearchResultsArtifact, TaskPackage


def filter_candidates(
    *,
    task_package: TaskPackage,
    search_results: SearchResultsArtifact,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> CandidateShortlist:
    payload = get_llm_provider().chat_json(
        system=_load_prompt("candidate_extract.md"),
        user_text=_build_user_text(task_package=task_package, search_results=search_results),
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
        response_format=_candidate_shortlist_response_format(),
        timeout=1200,
        attempts=3,
    )
    payload["publication_no"] = task_package.patent.publication_no
    _normalize_candidate_ids(payload)
    try:
        return CandidateShortlist.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(f"Invalid candidate shortlist JSON: {exc}\nPayload: {payload}") from exc


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
    compact_results = [
        {
            "result_id": result.result_id,
            "query_id": result.query_id,
            "query": result.query,
            "provider": result.provider,
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet[:700],
            "published_date": result.published_date,
        }
        for result in search_results.results[:250]
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
            "candidates": {"type": "array", "minItems": 15, "maxItems": 30, "items": candidate_schema},
        },
        "required": ["publication_no", "candidates"],
    }
    return {"type": "json_schema", "name": "candidate_shortlist", "strict": True, "schema": schema}
