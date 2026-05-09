"""Module-one pipeline."""

from __future__ import annotations

from pathlib import Path

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.fetcher.google_patents import fetch_patent
from patentradar.fetcher.pdf import download_pdf, render_claim_pages
from patentradar.llm.workers.decompose_worker import decompose_claims
from patentradar.schemas import TaskPackage


def run_decompose(
    publication_no: str,
    *,
    output_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> TaskPackage:
    fetched = fetch_patent(publication_no)
    images: list[bytes] | None = None
    source = "html"
    if fetched.has_claim_image_placeholders:
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
    return task_package
