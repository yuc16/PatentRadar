"""Evidence fetcher: HTML text extraction + PDF (text/image) multimodal extraction.

Returns a unified `FetchedEvidence` so module two's evidence_worker can pass
both text and key-page PNGs to the LLM via codex.chat_json(images=...).

HTML 端的图片证据（Tier 1）：扫描 <img>/<picture>/<figure>，对疑似产品图/
规格示意/拆解照打分排序，取 top-K 下载 PNG bytes 一起喂 LLM。这样模型能在
文字证据之外看到图表，对"数值/位置/连接关系藏在图里"的特征非常有用。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .image_utils import normalize_png
from .pdf import extract_pdf_evidence

logger = logging.getLogger(__name__)

_USER_AGENT = "patent-radar (python)"
# HTML 图片抽取上限：每 page 最多 3 张图。
# 配合 alt 去重（同 alt 只保留 score 最高的）—— 文章页 3 张同 alt 配图自然收敛
# 为 1 张；产品页 5+ 张不同 alt 的图（主图/尺寸图/拆解图/应用图）能保留前 3。
_HTML_IMG_TOP_K = 3
_HTML_IMG_MAX_BYTES = 2 * 1024 * 1024  # 2MB 单图上限，超大图（横幅 banner）直接跳过
_HTML_IMG_MIN_DIM = 200  # 最短边 < 200px 视为 icon / 小图，跳过
# URL 路径出现这些片段时加 +2 分：泛产品/规格/拆解类
_HTML_IMG_PATH_BOOSTS = (
    "spec", "specification", "datasheet",
    "detail", "details", "gallery", "teardown", "diagram", "figure", "schematic",
    "电池", "电芯", "规格", "尺寸", "拆解", "产品",
)
# URL 路径出现这些强信号片段时加 +3 分：显式产品页路径（最可能是主产品图）
_HTML_IMG_PATH_STRONG_BOOSTS = (
    "/product/", "/products/", "/datasheet/", "/spec/", "/specs/", "/teardown/",
)
# URL 路径出现这些片段时直接跳过（社交/分享/通用 UI 图标）
_HTML_IMG_PATH_SKIPS = (
    "/icon", "icons/", "/share/", "/logo", "logos/", "gravatar.com",
    "/avatar", "wp-content/themes/", "captcha", "tracking",
    "/sprite", ".svg",  # SVG 走另一条路径处理（多数 SVG 是装饰）
)
# alt/title 文本黑名单：命中即丢（噪声装饰图/营销组件）
_HTML_IMG_ALT_BLACKLIST = (
    "logo", "icon", "banner", "微信", "扫码", "二维码", "qrcode",
    "广告", "推广", "下载app", "客服", "header", "footer",
    "share", "login", "登录", "登陆", "注册", "captcha",
)
# 抓图最低 score 阈值：必须命中至少一个"真信号"
# (figure/picture 容器 +3、alt 关键词 +2、URL 路径 +2)，
# 单凭 "DOM 前半 +1" 或 "显式尺寸 +1" 不够 — 那是噪声常态。
_HTML_IMG_MIN_SCORE = 2
# PDF 关键页图固定 score：规格书/技术手册是高信号源，跟 HTML 里 score=4-5
# 的优质产品图同档；让 PDF 图和 HTML 图能在 worker 端按 score 全局排序时
# 互相竞争位次。
_PDF_IMAGE_SCORE = 5


@dataclass(frozen=True)
class FetchedPage:
    """Backwards-compatible struct used by older callers."""

    url: str
    title: str
    text: str


@dataclass(frozen=True)
class FetchedImage:
    """单张可喂给 vision LLM 的图片。

    - png: PNG 字节流（已下载/已渲染）
    - src_url: 图片所在容器页面 URL（HTML 时 = page URL；PDF 时 = PDF URL）
      用作下游 evidence[].url 引用，让人工核查能直接打开页面看图
    - alt: HTML <img alt> 文本；PDF 用 'PDF page N'
    - score: 启发式得分（HTML 见 _extract_html_images，PDF 固定 _PDF_IMAGE_SCORE）
      worker 端按 score 全局降序排，cap 切割时保留高分图。
    """

    png: bytes
    src_url: str
    alt: str = ""
    score: int = 0


@dataclass
class FetchedEvidence:
    """Unified evidence container for both HTML and PDF sources."""

    url: str
    title: str
    text: str
    images: list[FetchedImage] = field(default_factory=list)
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
    # 图片扫描必须在 decompose 之前（否则 <img> 也会被 strip）；先抓图，再 strip 文本元素
    images = _extract_html_images(soup=soup, page_url=url, keywords=keywords)
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = " ".join(soup.get_text(" ", strip=True).split())
    if not text:
        return FetchedEvidence(url=url, title=title, text="", images=images, source_kind="html")
    text = _extract_relevant_text(text, keywords, max_chars=max_chars)
    return FetchedEvidence(url=url, title=title, text=text, images=images, source_kind="html")


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
    # PDF 所有 image 都归属于该 PDF 的 url；alt 用 page number 标识便于 LLM 引用
    images: list[FetchedImage] = []
    for idx, png in enumerate(extraction.image_pngs, start=1):
        images.append(FetchedImage(png=png, src_url=url, alt=f"PDF page {idx}", score=_PDF_IMAGE_SCORE))
    return FetchedEvidence(
        url=url,
        title=title,
        text=text,
        images=images,
        source_kind=kind,
        matched_pages=list(extraction.matched_pages),
    )


def _extract_html_images(
    *,
    soup: BeautifulSoup,
    page_url: str,
    keywords: list[str],
) -> list[FetchedImage]:
    """从 HTML 抽取 <img>，按启发式排序，下载 top-K PNG 字节流。

    评分维度：
    - 容器：在 <figure>/<picture>/gallery class 里  +3
    - alt/title/周围文字含候选关键词           +2
    - URL 路径含 product/spec/teardown/规格...  +2
    - 显式 width/height >= 200px              +1（用作过滤 + 评分）
    - 在 page 前 50% DOM 顺序里                +1
    - URL 含 social / icon / sprite 等        直接跳过
    """
    candidates: list[tuple[int, str, str]] = []  # (score, abs_url, alt)
    keyword_set = {k.strip().lower() for k in (keywords or []) if k and k.strip()}
    all_imgs = soup.find_all("img")
    total = max(len(all_imgs), 1)
    for idx, img in enumerate(all_imgs):
        src = img.get("data-src") or img.get("data-original") or img.get("src") or ""
        if not src or src.startswith("data:"):
            continue
        abs_url = urljoin(page_url, src)
        lowered_url = abs_url.lower()
        if any(skip in lowered_url for skip in _HTML_IMG_PATH_SKIPS):
            continue
        if not urlparse(abs_url).scheme.startswith("http"):
            continue
        # 尺寸过滤：HTML 显式 width/height 至少一边 < 200 → 跳过
        w = _parse_dimension(img.get("width"))
        h = _parse_dimension(img.get("height"))
        if w and w < _HTML_IMG_MIN_DIM:
            continue
        if h and h < _HTML_IMG_MIN_DIM:
            continue
        score = 0
        if w and h and (w >= _HTML_IMG_MIN_DIM and h >= _HTML_IMG_MIN_DIM):
            score += 1
        # 容器加分：在 figure/picture 内或 class 含 gallery/product/spec
        parent = img
        for _ in range(3):
            parent = parent.parent
            if parent is None:
                break
            if parent.name in ("figure", "picture"):
                score += 3
                break
            cls = " ".join(parent.get("class") or []).lower()
            if any(tok in cls for tok in ("gallery", "product", "spec", "datasheet", "detail")):
                score += 2
                break
        # alt/title 关键词命中
        alt = (img.get("alt") or "").strip()
        title_attr = (img.get("title") or "").strip()
        if _is_noisy_alt(alt) or _is_noisy_alt(title_attr):
            continue
        meta_text = f"{alt} {title_attr}".lower()
        if keyword_set and any(k in meta_text for k in keyword_set):
            score += 2
        # URL 路径加分：强信号 +3（显式 product/datasheet/spec 路径），普通信号 +2
        if any(boost in lowered_url for boost in _HTML_IMG_PATH_STRONG_BOOSTS):
            score += 3
        elif any(boost in lowered_url for boost in _HTML_IMG_PATH_BOOSTS):
            score += 2
        # 在 DOM 前 50% 加分（页面顶部 hero 图概率高）
        if idx < total / 2:
            score += 1
        candidates.append((score, abs_url, alt or title_attr))

    if not candidates:
        return []
    # 去重 1：同 URL 保留最高 score
    seen: dict[str, tuple[int, str]] = {}
    for score, url_, alt in candidates:
        prev = seen.get(url_)
        if prev is None or score > prev[0]:
            seen[url_] = (score, alt)
    # 去重 2：同 alt 保留 score 最高的（文章页常 3 张图共享文章标题 alt，但只有
    # 1 张是产品图——同 alt 即近似重复，避免把同主题的多张配图全部抓回来）
    by_alt: dict[str, tuple[int, str]] = {}  # alt_lower → (score, url)
    for url_, (score, alt) in seen.items():
        key = (alt or "").strip().lower()
        if not key:
            # alt 为空时不参与 alt-去重（产品图 alt 常空，按 URL 各算一条）
            by_alt[f"__noalt__{url_}"] = (score, url_)
            continue
        prev = by_alt.get(key)
        if prev is None or score > prev[0]:
            by_alt[key] = (score, url_)
    # 反查回 (url, score, alt) 形式
    deduped: dict[str, tuple[int, str]] = {}
    for key, (score, url_) in by_alt.items():
        alt_value = "" if key.startswith("__noalt__") else key
        deduped[url_] = (score, alt_value)
    ranked = sorted(deduped.items(), key=lambda kv: (-kv[1][0], kv[0]))
    images: list[FetchedImage] = []
    # 多抓几个备选（下载失败/转换失败的会跳过，仍能取到 _HTML_IMG_TOP_K 张）
    for url_, (score, alt) in ranked[: max(_HTML_IMG_TOP_K * 4, 4)]:
        # score 阈值：见 _HTML_IMG_MIN_SCORE 注释
        if score < _HTML_IMG_MIN_SCORE:
            continue
        png = _download_as_png(url_)
        if png is None:
            continue
        images.append(FetchedImage(png=png, src_url=page_url, alt=alt, score=score))
        if len(images) >= _HTML_IMG_TOP_K:
            break
    return images


def _is_noisy_alt(text: str) -> bool:
    """alt/title 是否属于噪声：纯数字 / 过短 / 文件名结尾 / 黑名单关键词。

    空字符串不算噪声（产品图常常 alt 为空，让 score 自己判）。
    """
    if not text:
        return False
    lowered = text.strip().lower()
    if lowered.isdigit():
        return True
    if len(lowered) < 3:
        return True
    # alt 直接拿文件名：title.gif / banner.jpg / img_001.png
    if lowered.endswith((".gif", ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".svg")):
        return True
    return any(kw in lowered for kw in _HTML_IMG_ALT_BLACKLIST)


def _parse_dimension(value) -> int | None:
    if not value:
        return None
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def _download_as_png(url: str, *, timeout: float = 15.0) -> bytes | None:
    """下载图片字节，统一归一化为 PNG（长边 ≤ 1024，转 RGB）。下载失败返回 None。

    大图（超过 _HTML_IMG_MAX_BYTES）直接跳过，避免一张 banner 把 LLM 上下文塞爆。
    """
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": _USER_AGENT})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("Image download failed url=%s error=%s", url, exc)
        return None
    content_type = response.headers.get("content-type", "").lower()
    if not any(t in content_type for t in ("image/", "octet-stream")):
        return None
    data = response.content
    if len(data) > _HTML_IMG_MAX_BYTES:
        logger.info("Image too large (%d bytes) url=%s, skipping", len(data), url)
        return None
    return normalize_png(data)


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
