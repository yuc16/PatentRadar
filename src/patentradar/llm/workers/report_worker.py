"""GPT-5.5 worker that generates the final markdown report.

Unlike module 1/2/3 workers which use strict json_schema, this one returns
free-form markdown text via provider.chat_text().
"""

from __future__ import annotations

import json
from importlib import resources

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.llm import get_llm_provider
from patentradar.schemas import (
    FullClaimChartReport,
    SimilarPatentSearchHint,
    TaskPackage,
)


def generate_report_markdown(
    *,
    task_package: TaskPackage,
    full_claim_chart_report: FullClaimChartReport,
    similar_patents_hint: SimilarPatentSearchHint | None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> str:
    user_text = _build_user_text(
        task_package=task_package,
        full_claim_chart_report=full_claim_chart_report,
        similar_patents_hint=similar_patents_hint,
    )
    markdown = get_llm_provider().chat_text(
        system=_load_prompt(),
        user_text=user_text,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="high",
        timeout=1800,
    )
    return _strip_markdown_fence(markdown)


def _load_prompt() -> str:
    return resources.files("patentradar.llm.prompts").joinpath("report.md").read_text(
        encoding="utf-8"
    )


def _build_user_text(
    *,
    task_package: TaskPackage,
    full_claim_chart_report: FullClaimChartReport,
    similar_patents_hint: SimilarPatentSearchHint | None,
) -> str:
    max_total_score = (
        max((c.total_score for c in full_claim_chart_report.top_competitors), default=0.0)
    )
    threshold = (
        similar_patents_hint.threshold if similar_patents_hint else 80.0
    )
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
            "claim_1_text": task_package.claim_1_text,
            "claim_1_features": [
                {"feature_id": f.feature_id, "feature_text": f.feature_text}
                for f in task_package.claim_1_features
            ],
            "all_claims_count": len(task_package.claims),
        },
        "top_competitors": [c.model_dump() for c in full_claim_chart_report.top_competitors],
        "excluded_candidates": [
            c.model_dump() for c in full_claim_chart_report.excluded_candidates
        ],
        "max_total_score": max_total_score,
        "infringement_risk_threshold": threshold,
        "infringement_risk_triggered": max_total_score >= threshold,
        "similar_patents_hint": (
            similar_patents_hint.model_dump() if similar_patents_hint else None
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _strip_markdown_fence(text: str) -> str:
    """LLM sometimes wraps the whole response in ```markdown ... ```. Strip."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop the opening fence line
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # drop the closing fence line if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
