"""Evidence fetcher: HTML text extraction + PDF (text/image) multimodal extraction.

Returns a unified `FetchedEvidence` so module two's evidence_worker can pass
both text and key-page PNGs to the LLM via codex.chat_json(images=...).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from .pdf import extract_pdf_evidence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedPage:
    """Backwards-compatible struct used by older callers."""

    url: str
    title: str
    text: str


@dataclass
class FetchedEvidence:
    """Unified evidence container for both HTML and PDF sources."""

    url: str
    title: str
    text: str
    images: list[bytes] = field(default_factory=list)
    source_kind: str = "html"  # "html" | "pdf_text" | "pdf_mixed" | "pdf_image" | "skipped"
    matched_pages: list[int] = field(default_factory=list)


def fetch_evidence(
    url: str,
    *,
    keywords: list[str] | None = None,
    max_chars: int = 6000,
    timeout: float = 30.0,
) -> FetchedEvidence | None:
    """Fetch a URL and return text + (for PDFs) key-page images.

    Returns None on hard failures (network/HTTP). Returns an empty-ish
    FetchedEvidence (text="") when the URL is reachable but yields nothing
    useful; callers may still use it as a "we tried this URL" marker.
    """
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={"User-Agent": "patent-radar (python)"},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("Fetch evidence failed url=%s error=%s", url, exc)
        return None

    content_type = response.headers.get("content-type", "").lower()
    is_pdf = "pdf" in content_type or url.lower().endswith(".pdf")

    if is_pdf:
        return _extract_pdf(url=url, pdf_bytes=response.content, keywords=keywords or [], max_chars=max_chars)

    if "html" not in content_type and "text" not in content_type:
        # Some other binary; skip rather than false-positive.
        return None

    return _extract_html(url=url, html=response.text, keywords=keywords or [], max_chars=max_chars)


def fetch_page_text(
    url: str,
    *,
    keywords: list[str] | None = None,
    max_chars: int = 6000,
    timeout: float = 30.0,
) -> FetchedPage | None:
    """Backwards-compatible wrapper. Returns None for PDF-only URLs to keep
    legacy callers from breaking; modern code should use `fetch_evidence`."""
    evidence = fetch_evidence(url, keywords=keywords, max_chars=max_chars, timeout=timeout)
    if evidence is None or not evidence.text:
        return None
    return FetchedPage(url=evidence.url, title=evidence.title, text=evidence.text)


def _extract_html(*, url: str, html: str, keywords: list[str], max_chars: int) -> FetchedEvidence:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = " ".join(soup.get_text(" ", strip=True).split())
    if not text:
        return FetchedEvidence(url=url, title=title, text="", source_kind="html")
    text = _extract_relevant_text(text, keywords, max_chars=max_chars)
    return FetchedEvidence(url=url, title=title, text=text, source_kind="html")


def _extract_pdf(*, url: str, pdf_bytes: bytes, keywords: list[str], max_chars: int) -> FetchedEvidence:
    extraction = extract_pdf_evidence(pdf_bytes, keywords=keywords)
    text = "\n\n--page-break--\n\n".join(extraction.text_segments)[:max_chars]
    if extraction.text_segments and extraction.image_pngs:
        kind = "pdf_mixed"
    elif extraction.image_pngs:
        kind = "pdf_image"
    elif extraction.text_segments:
        kind = "pdf_text"
    else:
        kind = "skipped"
    title = url.rsplit("/", 1)[-1]
    return FetchedEvidence(
        url=url,
        title=title,
        text=text,
        images=list(extraction.image_pngs),
        source_kind=kind,
        matched_pages=list(extraction.matched_pages),
    )


def _extract_relevant_text(text: str, keywords: list[str], *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    windows: list[str] = []
    lowered = text.lower()
    for keyword in keywords:
        key = keyword.strip().lower()
        if not key:
            continue
        index = lowered.find(key)
        if index < 0:
            continue
        start = max(0, index - 900)
        end = min(len(text), index + 1800)
        windows.append(text[start:end])
        if sum(len(item) for item in windows) >= max_chars:
            break
    if not windows:
        return text[:max_chars]
    merged = "\n...\n".join(windows)
    return merged[:max_chars]
