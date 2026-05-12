"""Google Patents fetching and HTML claim extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

from patentradar.core.constants import GOOGLE_PATENTS_BASE, PATENT_COUNTRY_CODES
from patentradar.core.exceptions import PatentFetchError
from patentradar.schemas import Claim, PatentInfo

_PUB_NO_RE = re.compile(r"^[A-Z]{2}\d{6,}[A-Z]?\d?$")
_PUB_NO_IN_TEXT_RE = re.compile(r"([A-Z]{2})[-\s]*(\d{6,})[-\s]*([A-Z]?\d?)", re.I)
_PDF_RE = re.compile(r"https://patentimages\.storage\.googleapis\.com/[^\"']+\.pdf")
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Google Patents URL suffix per专利国家工作语言。其余语言走 /en（Google 默认）。
_URL_LANG_SUFFIX = {"zh": "zh", "ja": "ja", "ko": "ko", "de": "de", "fr": "fr", "ru": "ru"}
# Accept-Language header — primary语言 + en fallback。
_ACCEPT_LANG_PRIMARY = {
    "zh": "zh-CN,zh;q=0.9",
    "ja": "ja-JP,ja;q=0.9",
    "ko": "ko-KR,ko;q=0.9",
    "de": "de-DE,de;q=0.9",
    "fr": "fr-FR,fr;q=0.9",
    "ru": "ru-RU,ru;q=0.9",
}
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _patent_language(publication_no: str) -> str:
    prefix = publication_no[:2].upper()
    return PATENT_COUNTRY_CODES.get(prefix, ("", "en"))[1]


def _build_headers(language: str) -> dict[str, str]:
    primary = _ACCEPT_LANG_PRIMARY.get(language)
    accept_lang = f"{primary},en;q=0.5" if primary else "en;q=1.0"
    return {"User-Agent": _USER_AGENT, "Accept-Language": accept_lang}


@dataclass(frozen=True)
class PatentFetchResult:
    patent: PatentInfo
    claims: list[Claim]
    raw_html: str
    has_claim_image_placeholders: bool


def normalize_publication_no(publication_no: str) -> str:
    raw = publication_no.strip().upper()
    url_match = re.search(r"/PATENT/([^/?#]+)", raw)
    if url_match:
        raw = url_match.group(1)
    match = _PUB_NO_IN_TEXT_RE.search(raw)
    normalized = "".join(match.groups()) if match else raw
    normalized = normalized.replace(" ", "").replace("-", "")
    if not _PUB_NO_RE.match(normalized):
        raise PatentFetchError(f"Invalid patent publication number: {publication_no!r}")
    return normalized


def fetch_patent(
    publication_no: str, *, retries: int = 3, timeout: float = 60.0
) -> PatentFetchResult:
    publication_no = normalize_publication_no(publication_no)
    language = _patent_language(publication_no)
    suffix = _URL_LANG_SUFFIX.get(language, "en")
    url = f"{GOOGLE_PATENTS_BASE}/{publication_no}/{suffix}"
    html = _fetch_text(
        url=url, retries=retries, timeout=timeout, headers=_build_headers(language)
    )
    soup = BeautifulSoup(html, "lxml")
    claims, has_placeholders = _extract_claims(soup)
    if not claims:
        raise PatentFetchError(f"No claims extracted from {url}")

    pdf_match = _PDF_RE.search(html)
    patent = PatentInfo(
        publication_no=publication_no,
        title=_meta(soup, "DC.title") or "",
        applicants=(
            _main_dd_texts(soup, "assigneeOriginal")
            or _dc_contributors(soup, "assignee")
        ),
        inventors=_main_dd_texts(soup, "inventor")
        or _dc_contributors(soup, "inventor"),
        application_date=_date_text(soup, "filingDate"),
        google_patents_url=url,
        pdf_url=pdf_match.group(0) if pdf_match else "",
        fetched_at=datetime.now(_SHANGHAI_TZ).isoformat(timespec="seconds"),
    )
    return PatentFetchResult(
        patent=patent,
        claims=claims,
        raw_html=html,
        has_claim_image_placeholders=has_placeholders,
    )


def _fetch_text(
    *, url: str, retries: int, timeout: float, headers: dict[str, str]
) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = client.get(url)
                if response.status_code != 200:
                    raise PatentFetchError(f"HTTP {response.status_code}: {url}")
                return response.text
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt == retries:
                break
    raise PatentFetchError(f"Failed to fetch {url}: {last_exc}") from last_exc


def _extract_claims(soup: BeautifulSoup) -> tuple[list[Claim], bool]:
    section = soup.find("section", {"itemprop": "claims"})
    if not section:
        return [], False
    claims_root = (
        section.find("div", class_="claims", attrs={"lang": "ZH"})
        or section.find("div", class_="claims")
        or section
    )
    claim_tags = claims_root.find_all(
        "div", id=re.compile(r"^(?:[a-z]{2}-)?cl0*\d+$", re.I)
    )
    claims: list[Claim] = []
    has_placeholders = False
    seen: set[tuple[int, str]] = set()
    for tag in claim_tags:
        if not isinstance(tag, Tag):
            continue
        claim_no = _claim_number(tag)
        if claim_no is None:
            continue
        has_placeholders = has_placeholders or bool(
            tag.find(class_="patent-image-not-available")
        )
        claim_text = _claim_text(tag)
        if not claim_text:
            continue
        dedupe_key = (claim_no, claim_text[:30])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        claims.append(
            Claim(
                claim_no=claim_no,
                claim_text=claim_text,
                features=[],
            )
        )
    claims.sort(key=lambda item: item.claim_no)
    return claims, has_placeholders


def _claim_number(tag: Tag) -> int | None:
    raw = tag.get("num") or tag.get("id", "")
    match = re.search(r"(\d+)$", str(raw))
    if not match:
        return None
    return int(match.group(1))


def _claim_text(tag: Tag) -> str:
    parts: list[str] = []
    for item in tag.find_all("div", class_="claim-text"):
        text = item.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", {"name": name})
    if tag and tag.get("content"):
        return str(tag["content"]).strip() or None
    return None


def _dc_contributors(soup: BeautifulSoup, scheme: str) -> list[str]:
    values: list[str] = []
    for tag in soup.find_all("meta", {"name": "DC.contributor", "scheme": scheme}):
        text = str(tag.get("content") or "").strip()
        if text and text not in values:
            values.append(text)
    return values


def _main_dd_texts(soup: BeautifulSoup, itemprop: str) -> list[str]:
    values: list[str] = []
    for tag in soup.find_all("dd", {"itemprop": itemprop}):
        text = tag.get_text(" ", strip=True)
        if text and text not in values:
            values.append(text)
    return values


def _date_text(soup: BeautifulSoup, itemprop: str) -> str:
    tag = soup.find(attrs={"itemprop": itemprop})
    if not tag:
        return ""
    raw = (
        tag.get("datetime")
        or tag.get("content")
        or tag.get("title")
        or tag.get_text(" ", strip=True)
    )
    return _normalize_date(str(raw) if raw else "")


def _normalize_date(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", raw)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    match = re.search(r"(\d{4})(\d{2})(\d{2})", raw)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m}-{d}"
    return raw
