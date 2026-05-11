"""Module four report pipeline.

Flow:
1. Load task_package.json + top5_full_claim_chart.json
2. Check max(top_competitors[].total_score). If >= 80, build a Google Patents
   Advanced Search deep link (same country + same applicant + same title) for
   the reviewer to open in a browser. No automated crawling — Google Patents'
   xhr endpoint rate-limits and family-dedupes, neither of which we want.
3. Single LLM call: generate the full markdown report from
   task_package + full_claim_chart + similar_patents hint
4. Save report.md (+ similar_patents.json for traceability)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.llm.workers.report_worker import generate_report_markdown
from patentradar.schemas import (
    FullClaimChartReport,
    SimilarPatentSearchHint,
    TaskPackage,
)

from .similar_patents import INFRINGEMENT_RISK_THRESHOLD, build_similar_patent_hint

logger = logging.getLogger(__name__)


def run_report(
    *,
    task_package: TaskPackage,
    full_claim_chart_report: FullClaimChartReport,
    output_dir: Path,
    threshold: float = INFRINGEMENT_RISK_THRESHOLD,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    max_total_score = (
        max((c.total_score for c in full_claim_chart_report.top_competitors), default=0.0)
    )
    logger.info(
        "module4 report start publication=%s max_total_score=%.2f threshold=%.2f",
        task_package.patent.publication_no, max_total_score, threshold,
    )

    similar_hint: SimilarPatentSearchHint | None = None
    if max_total_score >= threshold:
        similar_hint = build_similar_patent_hint(
            task_package=task_package,
            triggered_by_score=max_total_score,
        )
        _write_json(output_dir / "similar_patents.json", similar_hint.model_dump())
        logger.info(
            "module4 similar-patent deep link generated url=%s",
            similar_hint.google_patents_search_url,
        )

    markdown = generate_report_markdown(
        task_package=task_package,
        full_claim_chart_report=full_claim_chart_report,
        similar_patents_hint=similar_hint,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    report_path = output_dir / "report.md"
    report_path.write_text(markdown + "\n", encoding="utf-8")
    logger.info(
        "module4 report done publication=%s output=%s elapsed_ms=%d",
        task_package.patent.publication_no,
        report_path,
        int((time.perf_counter() - started) * 1000),
    )
    return report_path


def load_task_package(path: Path) -> TaskPackage:
    return TaskPackage.model_validate(_read_json(path))


def load_full_claim_chart(path: Path) -> FullClaimChartReport:
    return FullClaimChartReport.model_validate(_read_json(path))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
