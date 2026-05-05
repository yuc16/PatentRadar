"""Google Patents 抓取与权利要求 1 抽取。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from ..config import PATENT_FETCH_TIMEOUT
from ..schemas import PatentMeta

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"}

PUB_NO_RE = re.compile(r"^[A-Z]{2}\d{6,}[A-Z]?\d?$")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class PatentFetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    meta: PatentMeta
    claim_1_text: str  # HTML 抽取的权要 1 文字（公式可能残缺）
    claims_block: str  # 完整 claims section 文本（调试用）
    pdf_url: str | None
    raw_html: str
    has_formula_loss: bool  # 权要 1 内是否检测到 patent-image-not-available


def normalize_publication_no(pub_no: str) -> str:
    n = pub_no.strip().upper().replace(" ", "")
    if not PUB_NO_RE.match(n):
        raise PatentFetchError(f"不像有效的专利公开号: {pub_no!r}")
    return n


def fetch_patent(pub_no: str, *, retries: int = 3) -> FetchResult:
    """抓取专利页面，抽取权要 1 + 元数据 + PDF 链接 + 公式残缺标记。

    对网络抖动（SSL 握手 / 连接被对端关闭 / 读超时）自动重试，最多 ``retries`` 次。
    """
    import time

    pub_no = normalize_publication_no(pub_no)
    url = f"https://patents.google.com/patent/{pub_no}/zh"
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(
                timeout=PATENT_FETCH_TIMEOUT,
                follow_redirects=True,
                headers=HEADERS,
            ) as cli:
                r = cli.get(url)
                if r.status_code != 200:
                    raise PatentFetchError(f"HTTP {r.status_code}: {url}")
                html = r.text
            break
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 * attempt)
                continue
            raise PatentFetchError(f"{exc.__class__.__name__}: {exc}") from exc
    else:  # pragma: no cover - 上面的 break 一定会执行或 raise
        if last_exc:
            raise PatentFetchError(str(last_exc))

    soup = BeautifulSoup(html, "lxml")
    title = _meta(soup, "DC.title")
    assignees = [a.get_text(strip=True) for a in soup.find_all("dd", {"itemprop": "assigneeOriginal"})]
    inventors = [i.get_text(strip=True) for i in soup.find_all("dd", {"itemprop": "inventor"})]

    claim1_text, claims_block, has_formula_loss = _extract_claim_1(soup)
    if not claim1_text:
        raise PatentFetchError(f"未能从页面抽取权利要求 1: {url}")

    pdf_match = re.search(
        r"https://patentimages\.storage\.googleapis\.com/[^\"']+\.pdf", html
    )
    pdf_url = pdf_match.group(0) if pdf_match else None

    meta = PatentMeta(
        publication_no=pub_no,
        title=title,
        assignees=assignees,
        inventors=inventors,
        source_url=url,
        fetched_at=datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds"),
    )
    return FetchResult(
        meta=meta,
        claim_1_text=claim1_text,
        claims_block=claims_block,
        pdf_url=pdf_url,
        raw_html=html,
        has_formula_loss=has_formula_loss,
    )


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", {"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip() or None
    return None


def _extract_claim_1(soup: BeautifulSoup) -> tuple[str, str, bool]:
    """返回 (权要 1 文字, 完整 claims 段, 公式是否残缺)。

    "公式残缺" = 权要 1 容器内出现 ``<span class="patent-image-not-available">``。
    Google Patents 用该标签占位被跳过的公式 / 图片。
    """
    section = soup.find("section", {"itemprop": "claims"})
    claims_block = section.get_text("\n", strip=True) if section else ""

    cl1 = None
    if section:
        cl1 = section.find("div", id=re.compile(r"^[a-z]{2}-cl0*1$", re.I))
        if cl1 is None:
            cl1 = section.find("div", attrs={"num": re.compile(r"^0*1$")})

    if cl1:
        has_loss = bool(cl1.find("span", class_="patent-image-not-available"))
        parts = [p.get_text(" ", strip=True) for p in cl1.find_all("div", class_="claim-text")]
        parts = [p for p in parts if p]
        if parts:
            return "\n".join(parts), claims_block, has_loss

    # 兜底：从 claims_block 用正则切第一条
    if claims_block:
        m = re.search(r"^\s*1[\.\s、](.*?)(?=\n\s*2[\.\s、])", claims_block, re.S | re.M)
        if m:
            text = ("1." + m.group(1)).strip()
            # 兜底路径无法精确判定 patent-image-not-available 是否在权要 1 内
            # 保守认为：若 claims_block 含该标记，整篇有公式残缺
            has_loss = "patent-image-not-available" in str(section) if section else False
            return text, claims_block, has_loss

    return "", claims_block, False
