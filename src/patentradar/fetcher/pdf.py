"""PDF download and claim-page rendering."""

from __future__ import annotations

import re

import httpx
import pymupdf

from patentradar.core.exceptions import PatentFetchError

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
