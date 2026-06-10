"""GPT-5.5 worker for module-two search query generation."""

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
from patentradar.llm.structured import generate_validated
from patentradar.schemas import QueryPlan, TaskPackage


def generate_query_plan(
    *,
    task_package: TaskPackage,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> QueryPlan:
    def _parse(payload: dict[str, Any]) -> QueryPlan:
        payload["publication_no"] = task_package.patent.publication_no
        try:
            return QueryPlan.model_validate(payload)
        except ValidationError as exc:
            raise LLMOutputError(f"Invalid query plan JSON: {exc}\nPayload: {payload}") from exc

    return generate_validated(
        system=_load_prompt("query_generation.md"),
        user_text=_build_user_text(task_package),
        parse=_parse,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
        response_format=_query_plan_response_format(),
        timeout=900,
        attempts=3,
    )


def _load_prompt(name: str) -> str:
    return resources.files("patentradar.llm.prompts").joinpath(name).read_text(encoding="utf-8")


def _build_user_text(task_package: TaskPackage) -> str:
    patent = task_package.patent
    claim_features = [
        {"feature_id": feature.feature_id, "feature_text": feature.feature_text}
        for feature in task_package.claim_1_features
    ]
    display_name, working_lang = PATENT_COUNTRY_CODES.get(
        patent.country_code, (patent.country_code or "Unknown", "en")
    )
    payload = {
        "publication_no": patent.publication_no,
        "patent_country": {
            "code": patent.country_code,
            "display_name": display_name,
            "working_language": working_lang,
        },
        "title": patent.title,
        "applicants": patent.applicants,
        "application_date": patent.application_date,
        "technology_tag": task_package.technology_tag,
        "claim_1_text": task_package.claim_1_text,
        "claim_1_features": claim_features,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _query_plan_response_format() -> dict[str, Any]:
    query_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query_id": {"type": "string", "pattern": "^Q\\d{2}$"},
            "query": {"type": "string"},
            "intent": {
                "type": "string",
                "enum": [
                    "claim_feature",
                    "market_name",
                    "specification",
                    "industry_company",
                    "launch_date",
                    "evidence",
                ],
            },
            "language": {"type": "string", "enum": ["zh", "en", "mixed"]},
            "target_feature_ids": {
                "type": "array",
                "items": {"type": "string", "pattern": "^C1-F\\d+$"},
            },
            "preferred_providers": {
                "type": "array",
                "items": {"type": "string", "enum": ["tavily", "bocha", "exa", "brave"]},
            },
        },
        "required": [
            "query_id",
            "query",
            "intent",
            "language",
            "target_feature_ids",
            "preferred_providers",
        ],
    }
    self_signals_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "domains": {"type": "array", "items": {"type": "string"}},
            "aliases": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["domains", "aliases"],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "publication_no": {"type": "string"},
            "claim_1_summary": {"type": "string"},
            "applicant_self_signals": self_signals_schema,
            "queries": {"type": "array", "minItems": 30, "maxItems": 50, "items": query_schema},
        },
        "required": ["publication_no", "claim_1_summary", "applicant_self_signals", "queries"],
    }
    return {"type": "json_schema", "name": "query_plan", "strict": True, "schema": schema}
