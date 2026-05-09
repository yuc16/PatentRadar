"""Module-one pipeline."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.fetcher.google_patents import fetch_patent
from patentradar.fetcher.pdf import download_pdf, render_claim_pages
from patentradar.llm.workers.decompose_worker import decompose_claims
from patentradar.schemas import TaskPackage

logger = logging.getLogger(__name__)


def run_decompose(
    publication_no: str,
    *,
    output_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> TaskPackage:
    started = time.perf_counter()
    fetched = fetch_patent(publication_no)
    images: list[bytes] | None = None
    source = "html"
    if fetched.has_claim_image_placeholders:
        logger.info(
            "decompose PDF vision triggered publication_no=%s claim_count=%d pdf_url=%s",
            fetched.patent.publication_no,
            len(fetched.claims),
            bool(fetched.patent.pdf_url),
        )
        pdf_bytes = download_pdf(fetched.patent.pdf_url)
        images = render_claim_pages(pdf_bytes)
        source = "pdf_vision"

    task_package = decompose_claims(
        patent=fetched.patent,
        html_claims=fetched.claims,
        images=images,
        source=source,
        model=model,
        reasoning_effort=reasoning_effort,
    )

    if output_dir is not None:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "task_package.json").write_text(
            task_package.model_dump_json(ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "decompose completed publication_no=%s source=%s claim_count=%d technology_tag=%s elapsed_ms=%d",
        task_package.patent.publication_no,
        task_package.claims_source,
        len(task_package.claims),
        task_package.technology_tag,
        elapsed_ms,
    )
    return task_package
