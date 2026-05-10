"""PDF download and claim-page rendering."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx
import pymupdf

from patentradar.core.exceptions import PatentFetchError

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}
_TITLE_PAGE_MARKERS = ("(54)发明名称", "(57)摘要", "(73)专利权人", "授权公告号", "公开日")


def download_pdf(url: str, *, timeout: float = 120.0) -> bytes:
    if not url:
        raise PatentFetchError("PDF url is empty")
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=_HEADERS) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def render_claim_pages(pdf_bytes: bytes, *, dpi: int = 180) -> list[bytes]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages: list[bytes] = []
    try:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            text = page.get_text()
            normalized = re.sub(r"\s+", "", text)
            if any(marker.replace(" ", "") in normalized for marker in _TITLE_PAGE_MARKERS):
                continue
            if "权利要求书" in normalized:
                pixmap = page.get_pixmap(dpi=dpi)
                pages.append(pixmap.tobytes("png"))
            elif pages and "说明书" in normalized:
                break
    finally:
        doc.close()
    if not pages:
        raise PatentFetchError("Could not locate claim pages in PDF")
    return pages


@dataclass(frozen=True)
class PdfExtraction:
    """Result of evidence-driven PDF extraction.

    `text_segments` are extracted from pages where the text layer has enough
    content (≥ text_threshold chars after stripping). `image_pngs` are PNG
    bytes rendered from pages whose text layer is sparse (scanned/image-heavy)
    so the LLM's multimodal channel can still parse them (specs tables etc).
    """

    text_segments: list[str]
    image_pngs: list[bytes]
    page_count: int
    matched_pages: list[int]


def extract_pdf_evidence(
    pdf_bytes: bytes,
    *,
    keywords: list[str],
    max_pages: int = 5,
    max_pdf_pages: int = 200,
    text_threshold: int = 200,
    dpi: int = 120,
) -> PdfExtraction:
    """Extract evidence from a PDF by locating keyword-matched pages, then
    routing each matched page by content shape: text-rich → text segment;
    text-sparse → render PNG for multimodal input.

    Args:
        pdf_bytes: raw PDF.
        keywords: terms to locate "interesting" pages (candidate names + claim
            feature keywords). Empty falls back to first 3 pages.
        max_pages: hard cap on returned pages (text + image combined). 5 pages
            keeps batch context manageable while covering most spec books.
        max_pdf_pages: skip-and-log if the PDF has more pages than this
            (likely an annual report / standards manual; not worth opening).
        text_threshold: a page with strip-text shorter than this is treated as
            scanned/image-heavy and rendered to PNG.
        dpi: render DPI for image pages. 120 keeps PNG ~150KB while remaining
            legible for tables.

    Returns:
        PdfExtraction. May contain empty text_segments and image_pngs if the
        PDF is unreadable; caller should treat that as "no evidence here".
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises various
        logger.info("PDF open failed: %s", exc)
        return PdfExtraction(text_segments=[], image_pngs=[], page_count=0, matched_pages=[])
    try:
        if doc.page_count > max_pdf_pages:
            logger.info(
                "PDF too long page_count=%d (cap=%d), skipping", doc.page_count, max_pdf_pages
            )
            return PdfExtraction(
                text_segments=[],
                image_pngs=[],
                page_count=doc.page_count,
                matched_pages=[],
            )

        target_pages = _locate_target_pages(doc, keywords=keywords)
        target_pages = sorted(target_pages)[:max_pages]

        text_segments: list[str] = []
        image_pngs: list[bytes] = []
        for page_num in target_pages:
            page = doc[page_num]
            stripped_text = page.get_text().strip()
            if len(stripped_text) >= text_threshold:
                text_segments.append(f"[page {page_num + 1}]\n{stripped_text}")
            else:
                pixmap = page.get_pixmap(dpi=dpi)
                image_pngs.append(pixmap.tobytes("png"))
        return PdfExtraction(
            text_segments=text_segments,
            image_pngs=image_pngs,
            page_count=doc.page_count,
            matched_pages=list(target_pages),
        )
    finally:
        doc.close()


def _locate_target_pages(doc: "pymupdf.Document", *, keywords: list[str]) -> set[int]:
    """Find pages whose text layer hits any keyword. Falls back to the first
    3 pages when nothing matches (cover/spec pages are usually informative).
    Includes ±1 neighboring pages for context."""
    target: set[int] = set()
    if keywords:
        for kw in keywords:
            kw_clean = (kw or "").strip()
            if not kw_clean:
                continue
            for page_index in range(doc.page_count):
                if doc[page_index].search_for(kw_clean):
                    target.add(page_index)
                    if page_index > 0:
                        target.add(page_index - 1)
                    if page_index < doc.page_count - 1:
                        target.add(page_index + 1)
    if not target:
        target = set(range(min(3, doc.page_count)))
    return target
