"""Specification-page evidence helpers.

This module handles two evidence cases that generic search/extract misses:

1. Product-spec index pages that link to the real datasheet PDF/product page.
2. Datasheet PDFs whose key dimensions live on drawing pages rather than in the
   text layer extracted by Tavily/Exa.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from html import unescape
from urllib.parse import urljoin

import httpx
import pymupdf
from bs4 import BeautifulSoup

from . import config, evidence as evidence_strategy
from .llm import controller
from .search.base import ExtractedPage

logger = logging.getLogger("patentradar.evidence_specs")

_SPEC_LINK_LIMIT = 6
_VISION_IMAGE_LIMIT = 3
_PDF_TIMEOUT = 45
_DIMENSION_LINE_RE = re.compile(
    r"(?i)(dimension|dimensions|cell dimension|size|length|width|thickness|"
    r"尺寸|电芯尺寸|长度|宽度|厚度|外形尺寸|重量|weight|capacity|energy|容量|能量|电压|voltage)"
)
_DIMENSION_VALUE_RE = re.compile(
    r"(?i)(?:\d+(?:\.\d+)?\s*(?:mm|cm|ah|wh|kwh|v|g|kg|mΩ|mohm)|"
    r"\d+(?:\.\d+)?\s*[x×*]\s*\d+(?:\.\d+)?(?:\s*[x×*]\s*\d+(?:\.\d+)?)?)"
)


def discover_spec_links(
    page: ExtractedPage,
    *,
    company: str,
    product: str,
    aliases: list[str] | tuple[str, ...],
    industry_tag: str | None = None,
    limit: int = _SPEC_LINK_LIMIT,
) -> list[tuple[str, str]]:
    """Extract likely product-spec links from a specification index page."""
    if not _is_spec_index_context(page, industry_tag=industry_tag):
        return []
    candidates: dict[str, tuple[int, str]] = {}
    for text, href in _iter_links(page):
        try:
            url = evidence_strategy.canonicalize_url(urljoin(page.url, href))
        except ValueError:
            logger.info("跳过畸形规格链接: base=%s href=%s", page.url[:80], str(href)[:80])
            continue
        if not url or url == page.url:
            continue
        if _is_tracking_or_ad_url(url):
            continue
        label = unescape(re.sub(r"\s+", " ", text or "")).strip()
        haystack = f"{label} {url}"
        score = _link_score(
            haystack,
            company=company,
            product=product,
            aliases=aliases,
            industry_tag=industry_tag,
        )
        if score < 4:
            continue
        if not evidence_strategy.should_read_url(url, label, industry_tag=industry_tag):
            continue
        old = candidates.get(url)
        if old is None or score > old[0]:
            candidates[url] = (score, label)
    return [
        (url, label)
        for url, (score, label) in sorted(
            candidates.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[:limit]
    ]


def augment_spec_page(
    page: ExtractedPage,
    *,
    company: str,
    product: str,
    aliases: list[str] | tuple[str, ...],
    industry_tag: str | None = None,
) -> ExtractedPage:
    """Prepend structured dimensions/spec facts to extracted evidence text."""
    facts = extract_spec_facts(page.text)
    visual_facts: list[str] = []
    if _needs_pdf_drawing_vision(page, facts, industry_tag=industry_tag):
        visual_facts = _extract_pdf_drawing_facts_with_vision(
            page.url,
            company=company,
            product=product,
            aliases=aliases,
        )

    if not facts and not visual_facts:
        return page

    lines = ["[结构化规格/尺寸抽取]"]
    if facts:
        lines.extend(f"- {fact}" for fact in facts)
    if visual_facts:
        lines.append("[GPT-5.5视觉读取PDF图纸页]")
        lines.extend(f"- {fact}" for fact in visual_facts)
    text = "\n".join(lines) + "\n\n" + (page.text or "")
    raw = dict(page.raw or {})
    raw["_spec_facts"] = facts
    raw["_vision_spec_facts"] = visual_facts
    return ExtractedPage(
        url=page.url,
        title=page.title,
        text=text,
        source=f"{page.source}+specfacts",
        raw=raw,
    )


def extract_spec_facts(text: str, *, limit: int = 18) -> list[str]:
    """Pull dense dimension/capacity/energy lines out of extracted text."""
    out: list[str] = []
    seen: set[str] = set()
    normalized = re.sub(r"[ \t]+", " ", text or "")
    for raw in re.split(r"[\r\n]+|(?<=。)\s+|(?<=;)\s+", normalized):
        line = raw.strip(" -|:：\t")
        if len(line) < 4 or len(line) > 380:
            continue
        if "](http" in line or line.startswith(("[", "+ [", "* [")):
            continue
        if not _DIMENSION_LINE_RE.search(line):
            continue
        if not _DIMENSION_VALUE_RE.search(line):
            continue
        key = re.sub(r"\s+", "", line.lower())
        if key in seen:
            continue
        out.append(line)
        seen.add(key)
        if len(out) >= limit:
            break

    compact_patterns = (
        r"(?i)(dimension|dimensions|size|尺寸|外形尺寸)\s*[:：]?\s*"
        r"(\d+(?:\.\d+)?\s*[x×*]\s*\d+(?:\.\d+)?\s*[x×*]\s*\d+(?:\.\d+)?\s*mm)",
        r"(?i)(length|width|thickness|长度|宽度|厚度)\s*[:：]?\s*"
        r"(\d+(?:\.\d+)?\s*mm)",
    )
    for pat in compact_patterns:
        for m in re.finditer(pat, normalized):
            fact = re.sub(r"\s+", " ", " ".join(m.groups())).strip()
            key = fact.lower()
            if key not in seen:
                out.insert(0, fact)
                seen.add(key)
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]


def _is_spec_index_context(page: ExtractedPage, *, industry_tag: str | None = None) -> bool:
    text = f"{page.url} {page.title} {page.text[:2000]}".lower()
    if evidence_strategy.source_type_from_url_title(page.url, page.title, industry_tag=industry_tag) != "产品手册":
        return False
    return any(
        hint in text
        for hint in (
            "datasheet list",
            "download",
            "specification pdf",
            "product specification",
            "规格书",
            "产品规格",
            "pdf",
        )
    )


def _iter_links(page: ExtractedPage) -> list[tuple[str, str]]:
    blob = "\n".join(
        part
        for part in (
            page.text or "",
            json.dumps(page.raw or {}, ensure_ascii=False),
        )
        if part
    )
    links: list[tuple[str, str]] = []
    for m in re.finditer(r"\[([^\]]{1,240})\]\((https?://[^)\s]+)\)", blob):
        links.append((m.group(1), m.group(2)))
    for m in re.finditer(r"(?is)<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", blob):
        text = BeautifulSoup(m.group(2), "html.parser").get_text(" ", strip=True)
        links.append((text, m.group(1)))
    for m in re.finditer(r"https?://[^\s\"'<>）)]+", blob):
        links.append(("", m.group(0)))
    return links


def _is_tracking_or_ad_url(url: str) -> bool:
    domain = evidence_strategy.domain_of(url)
    if not domain:
        return True
    if domain in {
        "bat.bing.com",
        "sp.analytics.yahoo.com",
        "analytics.twitter.com",
        "www.google-analytics.com",
        "googleads.g.doubleclick.net",
    }:
        return True
    if domain == "t.co" and "/i/adsct" in url:
        return True
    return False


def _link_score(
    text: str,
    *,
    company: str,
    product: str,
    aliases: list[str] | tuple[str, ...],
    industry_tag: str | None,
) -> int:
    score = 0
    low = text.lower()
    if any(h in low for h in ("datasheet", "specification", "product-specification", "规格书", ".pdf")):
        score += 2
    has_product = evidence_strategy._has_product_signal(  # noqa: SLF001
        text,
        "",
        "",
        product,
        aliases,
        industry_tag=industry_tag,
    )
    if has_product:
        score += 3
    has_company = evidence_strategy._has_company_signal(  # noqa: SLF001
        text,
        "",
        "",
        company,
        industry_tag=industry_tag,
    )
    if has_company:
        score += 3
    if not (has_product or has_company):
        return 0
    if re.search(r"(?i)\b\d{2,4}\s?ah\b", text):
        score += 1
    return score


def _needs_pdf_drawing_vision(
    page: ExtractedPage,
    facts: list[str],
    *,
    industry_tag: str | None = None,
) -> bool:
    low = f"{page.url} {page.title} {page.text[:6000]}".lower()
    if ".pdf" not in low:
        return False
    if evidence_strategy.source_type_from_url_title(page.url, page.title, industry_tag=industry_tag) != "产品手册":
        return False
    has_dimension_value = any(re.search(r"(?i)(dimension|尺寸|length|width|thickness|长度|宽度|厚度)", f) for f in facts)
    if has_dimension_value and any("x" in f.lower() or "×" in f or "长度" in f or "width" in f.lower() for f in facts):
        return False
    return any(
        hint in low
        for hint in (
            "cell dimension",
            "电芯尺寸",
            "refer to 8",
            "请参考本产品标准第 8",
            "请参考本产品标准第8",
            "drawing",
            "电芯图纸",
        )
    )


def _extract_pdf_drawing_facts_with_vision(
    url: str,
    *,
    company: str,
    product: str,
    aliases: list[str] | tuple[str, ...],
) -> list[str]:
    try:
        images = _render_pdf_dimension_pages(url)
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF drawing render failed url=%s error=%s", url, exc)
        return []
    if not images:
        return []

    system = (
        "你是电池产品规格书图纸页读取助手。只基于图片读取可见文字和尺寸标注，"
        "提取长宽厚、容量、电压、能量、重量等事实。不得推测。"
    )
    user = (
        f"候选公司：{company}\n"
        f"候选产品：{product}\n"
        f"别名：{', '.join(str(a) for a in aliases)}\n"
        "请读取这些PDF规格书图纸/尺寸页，输出严格JSON：\n"
        '{"facts":["尺寸/参数事实，保留单位和原文含义"],"notes":"无法读取时说明"}\n'
        "如果看到外形尺寸，请明确写成 length/width/thickness 或 长/宽/厚。"
    )
    try:
        data = controller.chat_json(
            system=system,
            user_text=user,
            images=images,
            model=config.REVIEWER.model or None,
            reasoning_effort="low",
            verbosity="low",
            timeout=240,
            fallback_label="pdf-vision",
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF drawing vision failed url=%s error=%s", url, exc)
        return []
    facts = data.get("facts") if isinstance(data, dict) else []
    out = [str(f).strip() for f in facts or [] if str(f).strip()]
    return out[:12]


def _render_pdf_dimension_pages(url: str) -> list[bytes]:
    with httpx.Client(
        timeout=_PDF_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "PatentRadar/1.0"},
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        pdf_bytes = resp.content
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_indices: list[int] = []
        for i in range(doc.page_count):
            text = doc[i].get_text() or ""
            norm = re.sub(r"\s+", " ", text).lower()
            if any(h in norm for h in ("drawing", "电芯图纸", "cell dimension", "电芯尺寸", "dimension")):
                page_indices.append(i)
        for i in range(max(0, doc.page_count - 3), doc.page_count):
            if i not in page_indices:
                page_indices.append(i)
        images: list[bytes] = []
        for i in page_indices[:_VISION_IMAGE_LIMIT]:
            pix = doc[i].get_pixmap(dpi=190)
            images.append(pix.tobytes("png"))
        return images
    finally:
        doc.close()


def page_to_cache_payload(page: ExtractedPage) -> dict:
    return asdict(page)
