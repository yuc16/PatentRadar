"""GPT-5.5 worker for complete claim decomposition."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import ValidationError

from patentradar.core.constants import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    TECHNOLOGY_TAGS,
    render_technology_tags_markdown,
)
from patentradar.core.exceptions import LLMOutputError
from patentradar.llm import codex
from patentradar.schemas import Claim, PatentInfo, TaskPackage


def decompose_claims(
    *,
    patent: PatentInfo,
    html_claims: list[Claim],
    images: list[bytes] | None,
    source: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> TaskPackage:
    prompt = _load_prompt()
    user_text = _build_user_text(patent=patent, html_claims=html_claims, source=source)
    payload = codex.chat_json(
        system=prompt,
        user_text=user_text,
        images=images or None,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
        response_format=_task_package_response_format(),
        timeout=1200,
        attempts=3,
    )
    return _task_package_from_payload(
        payload=payload,
        patent=patent,
        html_claims=html_claims,
        source=source,
        model=model,
        reasoning_effort=reasoning_effort,
    )


def _load_prompt() -> str:
    raw = resources.files("patentradar.llm.prompts").joinpath("decompose.md").read_text(
        encoding="utf-8"
    )
    # Substitute the technology tags placeholder so the prompt always reflects
    # configs/technology_tags.toml without needing manual edits in two places.
    return raw.replace("{{TECHNOLOGY_TAGS_DESCRIPTIONS}}", render_technology_tags_markdown())


def _build_user_text(*, patent: PatentInfo, html_claims: list[Claim], source: str) -> str:
    claims_payload = [
        {
            "claim_no": claim.claim_no,
            "claim_text": claim.claim_text,
        }
        for claim in html_claims
    ]
    vision_note = (
        "附件包含 Google Patents 官方 PDF 的权利要求书页面 PNG。HTML 中存在图片/公式占位，必须以图片为准还原完整权利要求。"
        if source == "pdf_vision"
        else "无附件图片。HTML 权利要求文本未检测到图片/公式占位，直接基于文本拆解。"
    )
    return (
        f"专利基础信息：\n{patent.model_dump_json(ensure_ascii=False, indent=2)}\n\n"
        f"{vision_note}\n\n"
        "Google Patents HTML 抽取到的全部权利要求如下：\n"
        f"{json.dumps(claims_payload, ensure_ascii=False, indent=2)}"
    )


def _task_package_from_payload(
    *,
    payload: dict[str, Any],
    patent: PatentInfo,
    html_claims: list[Claim],
    source: str,
    model: str,
    reasoning_effort: str,
) -> TaskPackage:
    if "patent" not in payload:
        payload["patent"] = patent.model_dump()
    else:
        payload["patent"] = {**patent.model_dump(), **dict(payload["patent"] or {})}

    payload["claims_source"] = source
    payload["model"] = model
    payload["reasoning_effort"] = reasoning_effort

    claim_1 = next((claim for claim in payload.get("claims", []) if claim.get("claim_no") == 1), None)
    if not claim_1:
        raise LLMOutputError("Invalid decompose JSON: claims must include claim_no=1")
    _normalize_feature_ids(payload)
    payload["claim_1_text"] = claim_1.get("claim_text", "")
    payload["claim_1_features"] = claim_1.get("features", [])

    try:
        task_package = TaskPackage.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(f"Invalid decompose JSON: {exc}\nPayload: {payload}") from exc

    _validate_against_html(task_package=task_package, html_claims=html_claims, source=source)
    return task_package


def _normalize_feature_ids(payload: dict[str, Any]) -> None:
    for claim in payload.get("claims", []):
        claim_no = claim.get("claim_no")
        for index, feature in enumerate(claim.get("features", []), start=1):
            feature["feature_id"] = f"C{claim_no}-F{index}"


def _validate_against_html(*, task_package: TaskPackage, html_claims: list[Claim], source: str) -> None:
    if source == "pdf_vision" and len(task_package.claims) < len(html_claims):
        raise LLMOutputError(
            f"PDF vision claim count too low: LLM={len(task_package.claims)} HTML={len(html_claims)}"
        )
    if source != "pdf_vision" and len(task_package.claims) != len(html_claims):
        raise LLMOutputError(
            f"HTML claim count mismatch: LLM={len(task_package.claims)} HTML={len(html_claims)}"
        )
    expected_numbers = [claim.claim_no for claim in html_claims]
    actual_numbers = [claim.claim_no for claim in task_package.claims]
    if source == "pdf_vision" and actual_numbers[: len(expected_numbers)] != expected_numbers:
        raise LLMOutputError(f"PDF vision claim numbers mismatch: LLM={actual_numbers} HTML={expected_numbers}")
    if source != "pdf_vision" and actual_numbers != expected_numbers:
        raise LLMOutputError(f"Claim numbers mismatch: LLM={actual_numbers} HTML={expected_numbers}")
    if task_package.technology_tag not in TECHNOLOGY_TAGS:
        raise LLMOutputError(f"Invalid technology_tag: {task_package.technology_tag}")
    if not task_package.claim_1_features:
        raise LLMOutputError("claim_1_features must not be empty")


def _task_package_response_format() -> dict[str, Any]:
    feature_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "feature_id": {"type": "string", "pattern": "^C\\d+-F\\d+$"},
            "feature_text": {"type": "string"},
        },
        "required": ["feature_id", "feature_text"],
    }
    claim_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_no": {"type": "integer"},
            "claim_text": {"type": "string"},
            "features": {"type": "array", "items": feature_schema},
        },
        "required": ["claim_no", "claim_text", "features"],
    }
    patent_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "publication_no": {"type": "string"},
            "title": {"type": "string"},
            "applicants": {"type": "array", "items": {"type": "string"}},
            "inventors": {"type": "array", "items": {"type": "string"}},
            "application_date": {"type": "string"},
            "google_patents_url": {"type": "string"},
            "pdf_url": {"type": "string"},
            "fetched_at": {"type": "string"},
        },
        "required": [
            "publication_no",
            "title",
            "applicants",
            "inventors",
            "application_date",
            "google_patents_url",
            "pdf_url",
            "fetched_at",
        ],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "patent": patent_schema,
            "technology_tag": {"type": "string", "enum": TECHNOLOGY_TAGS},
            "claims": {"type": "array", "items": claim_schema},
            "claims_source": {"type": "string", "enum": ["html", "pdf_vision"]},
            "model": {"type": "string"},
            "reasoning_effort": {"type": "string"},
        },
        "required": [
            "patent",
            "technology_tag",
            "claims",
            "claims_source",
            "model",
            "reasoning_effort",
        ],
    }
    return {
        "type": "json_schema",
        "name": "task_package",
        "strict": True,
        "schema": schema,
    }
