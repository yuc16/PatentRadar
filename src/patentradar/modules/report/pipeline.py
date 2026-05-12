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
    try:
        pdf_path = render_pdf(report_path)
        logger.info("module4 report pdf=%s", pdf_path)
    except Exception as exc:  # noqa: BLE001
        # PDF 渲染依赖系统层 pango/cairo；缺依赖时 md 仍然可用，不让整个流程跪
        logger.warning("module4 report PDF render failed (md still saved): %s", exc)
    logger.info(
        "module4 report done publication=%s output=%s elapsed_ms=%d",
        task_package.patent.publication_no,
        report_path,
        int((time.perf_counter() - started) * 1000),
    )
    return report_path


def render_pdf(md_path: Path) -> Path:
    """Markdown → PDF via WeasyPrint。中文走 macOS 系统字体 PingFang SC。"""
    import markdown
    from weasyprint import HTML

    html_body = markdown.markdown(
        md_path.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code"],
    )
    style = """
        @page { size: A4; margin: 18mm 14mm; }
        body { font-family: "PingFang SC", "Helvetica Neue", "Arial", sans-serif;
               font-size: 10.5pt; line-height: 1.55; color: #222; }
        h1 { font-size: 19pt; border-bottom: 2px solid #333; padding-bottom: 4pt; margin-top: 0; }
        h2 { font-size: 14pt; margin-top: 18pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }
        h3 { font-size: 12pt; color: #444; margin-top: 14pt; }
        h4, h5 { font-size: 11pt; color: #555; }
        /* table-layout: fixed → 每列等宽，避免「状态/feature_id」短列被挤到 1-2 字
           宽度后让 `明确不满足` 这种 4 字内容竖排。每行 break-inside: avoid 防止
           WeasyPrint 把行劈成两半（C3-F1 只剩 feature_id 那种）。*/
        table { border-collapse: collapse; width: 100%; margin: 6pt 0;
                table-layout: fixed; }
        th, td { border: 1px solid #888; padding: 4pt 6pt; font-size: 9pt;
                 vertical-align: top; word-break: normal; overflow-wrap: anywhere; }
        th { background: #f0f0f0; }
        tr { break-inside: avoid; page-break-inside: avoid; }
        a { color: #1a6dba; text-decoration: none; word-break: break-all; }
        blockquote { border-left: 3px solid #aaa; padding: 4pt 10pt; color: #555;
                     background: #fafafa; margin: 6pt 0; }
        code { background: #f3f3f3; padding: 0 3pt; border-radius: 2pt;
               font-family: "Menlo", "Courier New", monospace; font-size: 9.5pt; }
        pre code { display: block; padding: 8pt; }
    """
    html_full = f"""<!doctype html><html><head><meta charset='utf-8'>
<style>{style}</style></head><body>{html_body}</body></html>"""
    pdf_path = md_path.with_suffix(".pdf")
    HTML(string=html_full).write_pdf(pdf_path)
    return pdf_path


def load_task_package(path: Path) -> TaskPackage:
    return TaskPackage.model_validate(_read_json(path))


def load_full_claim_chart(path: Path) -> FullClaimChartReport:
    return FullClaimChartReport.model_validate(_read_json(path))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
