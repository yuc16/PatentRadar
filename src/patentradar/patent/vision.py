"""下载 Google Patents PDF 并渲染权利要求书页面为 PNG。"""

from __future__ import annotations

import re

import httpx
import pymupdf

from ..config import PATENT_FETCH_TIMEOUT

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def find_pdf_url(html: str) -> str | None:
    m = re.search(
        r"https://patentimages\.storage\.googleapis\.com/[^\"']+\.pdf", html
    )
    return m.group(0) if m else None


def download_pdf(url: str) -> bytes:
    with httpx.Client(
        timeout=PATENT_FETCH_TIMEOUT * 2,
        follow_redirects=True,
        headers={"User-Agent": _UA},
    ) as cli:
        r = cli.get(url)
        r.raise_for_status()
        return r.content


_TITLE_PAGE_MARKERS = ("(54)发明名称", "(57)摘要", "(73)专利权人", "授权公告号")


def render_claims_pages(pdf_bytes: bytes, *, dpi: int = 180) -> list[bytes]:
    """定位"权利要求书"页并渲染为 PNG bytes 列表。

    - 跳过扉页（含 (54)发明名称 / (57)摘要 等书目标记）；
    - 收集页脚含"权利要求书"的页；
    - 一旦进入"说明书"页则停止。
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages: list[bytes] = []
    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text()
        norm = re.sub(r"\s+", "", text)
        if any(m.replace(" ", "") in norm for m in _TITLE_PAGE_MARKERS):
            continue  # 扉页
        if "权利要求书" in norm:
            pix = page.get_pixmap(dpi=dpi)
            pages.append(pix.tobytes("png"))
        elif pages and "说明书" in norm:
            break
    doc.close()
    return pages
