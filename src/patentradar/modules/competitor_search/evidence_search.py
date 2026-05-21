"""Evidence search context builder for step 4."""

from __future__ import annotations

from dataclasses import dataclass, field

from patentradar.core.constants import get_recommended_sites_for_tag
from patentradar.fetcher.web_fetcher import fetch_evidence
from patentradar.schemas import ApplicantSelfSignals, Candidate, ClaimFeature, SearchResult
from patentradar.search import SearchRouter


@dataclass
class CandidateEvidenceContext:
    candidate: Candidate
    queries: list[str]
    search_results: list[SearchResult]
    fetched_pages: list[dict[str, str]]
    # Multimodal channel: list of (image_png_bytes, source_url, page_no?) so the
    # LLM call can include key spec-table / scanned-PDF pages it can read.
    fetched_images: list[dict] = field(default_factory=list)


def build_initial_evidence_context(
    *,
    publication_no: str,
    candidate: Candidate,
    claim_features: list[ClaimFeature],
    router: SearchRouter,
    self_signals: ApplicantSelfSignals | None = None,
    technology_tag: str | None = None,
) -> CandidateEvidenceContext:
    """3 阶段 fetch（按优先级）：
      A. seed_pages：step3 已 vetted 的 source_urls（最优先）
      B. site-focused：`<product> site:<recommended_host>` 单独跑一轮，
         先把推荐站内的命中 URL 抓回 —— 用户在 configs/technology_tags.toml
         配置的垂类网站此时优先被覆盖
      C. general：通用 query（中英文产品+特征关键词）补其他来源
    """
    # A. seed pages
    seed_pages, seed_images = _fetch_url_list(
        candidate=candidate,
        claim_features=claim_features,
        urls=list(candidate.source_urls),
        max_pages=10,
        technology_tag=technology_tag,
    )
    seen_urls = {page["url"] for page in seed_pages}

    # B. site-focused round（先跑、先 fetch）
    site_queries = _build_site_only_queries(candidate, technology_tag)
    site_results: list[SearchResult] = []
    site_pages: list[dict[str, str]] = []
    site_images: list[dict] = []
    if site_queries:
        site_results = router.search_queries(
            publication_no=publication_no,
            queries=site_queries,
            query_id_prefix=f"{candidate.candidate_id}-S",
            max_results_per_query=5,
            self_signals=self_signals,
        ).results
        site_pages, site_images = fetch_relevant_pages(
            candidate=candidate,
            claim_features=claim_features,
            results=[r for r in site_results if r.url not in seen_urls],
            max_pages=8,
            technology_tag=technology_tag,
        )
        seen_urls.update(page["url"] for page in site_pages)

    # C. general queries（site: query 已不混在内）
    general_queries = _build_general_initial_queries(candidate, claim_features)
    general_results = router.search_queries(
        publication_no=publication_no,
        queries=general_queries,
        query_id_prefix=f"{candidate.candidate_id}-I",
        max_results_per_query=5,
        self_signals=self_signals,
    ).results
    extra_pages, extra_images = fetch_relevant_pages(
        candidate=candidate,
        claim_features=claim_features,
        results=[r for r in general_results if r.url not in seen_urls],
        max_pages=max(0, 12 - len(seed_pages) - len(site_pages)),
        technology_tag=technology_tag,
    )

    queries = list(site_queries) + list(general_queries)
    all_results = list(site_results) + list(general_results)
    pages = seed_pages + site_pages + extra_pages
    images = seed_images + site_images + extra_images
    return CandidateEvidenceContext(
        candidate=candidate,
        queries=queries,
        search_results=all_results,
        fetched_pages=pages,
        fetched_images=images,
    )


def build_gap_evidence_context(
    *,
    publication_no: str,
    candidate: Candidate,
    gap_features: list[ClaimFeature],
    router: SearchRouter,
    self_signals: ApplicantSelfSignals | None = None,
    technology_tag: str | None = None,
) -> CandidateEvidenceContext:
    # site-focused round 先跑（按缺口 feature 加站点修饰）
    site_queries = _build_site_gap_queries(candidate, gap_features, technology_tag)
    seen_urls: set[str] = set()
    site_results: list[SearchResult] = []
    site_pages: list[dict[str, str]] = []
    site_images: list[dict] = []
    if site_queries:
        site_results = router.search_queries(
            publication_no=publication_no,
            queries=site_queries,
            query_id_prefix=f"{candidate.candidate_id}-GS",
            max_results_per_query=5,
            self_signals=self_signals,
        ).results
        site_pages, site_images = fetch_relevant_pages(
            candidate=candidate,
            claim_features=gap_features,
            results=site_results,
            max_pages=6,
            technology_tag=technology_tag,
        )
        seen_urls.update(page["url"] for page in site_pages)

    # 通用 gap query 补其他来源
    general_queries = _build_general_gap_queries(candidate, gap_features)
    general_results = router.search_queries(
        publication_no=publication_no,
        queries=general_queries,
        query_id_prefix=f"{candidate.candidate_id}-G",
        max_results_per_query=5,
        self_signals=self_signals,
    ).results
    extra_pages, extra_images = fetch_relevant_pages(
        candidate=candidate,
        claim_features=gap_features,
        results=[r for r in general_results if r.url not in seen_urls],
        technology_tag=technology_tag,
    )
    queries = list(site_queries) + list(general_queries)
    results = list(site_results) + list(general_results)
    pages = site_pages + extra_pages
    images = site_images + extra_images
    return CandidateEvidenceContext(
        candidate=candidate,
        queries=queries,
        search_results=results,
        fetched_pages=pages,
        fetched_images=images,
    )


def build_initial_evidence_queries(
    *,
    candidate: Candidate,
    claim_features: list[ClaimFeature],
    technology_tag: str | None = None,
) -> list[str]:
    """合并版（site + general，保留向后兼容）。新代码请直接调
    `_build_site_only_queries` + `_build_general_initial_queries`。"""
    return _dedupe_queries(
        _build_site_only_queries(candidate, technology_tag)
        + _build_general_initial_queries(candidate, claim_features)
    )[:20]


def build_gap_evidence_queries(
    *,
    candidate: Candidate,
    gap_features: list[ClaimFeature],
    technology_tag: str | None = None,
) -> list[str]:
    """合并版（保留向后兼容）。新代码请直接调
    `_build_site_gap_queries` + `_build_general_gap_queries`。"""
    return _dedupe_queries(
        _build_site_gap_queries(candidate, gap_features, technology_tag)
        + _build_general_gap_queries(candidate, gap_features)
    )[:40]


def _build_general_initial_queries(
    candidate: Candidate, claim_features: list[ClaimFeature]
) -> list[str]:
    """初始 round 的通用 query（无 site: 修饰）—— 给 4 个 search provider 跑普通检索。"""
    product_zh = _product_label(candidate)
    product_en = _product_label_en(candidate)
    queries: list[str] = [
        f"{product_zh} 规格书 参数",
        f"{product_zh} 说明书 PDF",
        f"{product_zh} 官方 参数",
        f"{product_zh} 拆解 结构",
        f"{product_zh} 上市 日期 发布",
        f"{candidate.company} {candidate.product_name} 中国 市场",
    ]
    if product_en:
        queries.extend(
            [
                f"{product_en} datasheet specifications",
                f"{product_en} dimensions length width thickness",
                f"{product_en} press release launch date",
                f"{product_en} teardown review structure",
            ]
        )
    for feature in claim_features[:3]:
        queries.append(f"{product_zh} {feature.feature_text[:80]}")
        if product_en:
            queries.append(f"{product_en} {feature.feature_text[:80]}")
    return _dedupe_queries(queries)[:14]


def _build_site_only_queries(
    candidate: Candidate, technology_tag: str | None
) -> list[str]:
    """初始 round 的 site: 限定 query —— 优先在推荐垂类站点内检索候选。"""
    product_zh = _product_label(candidate)
    product_en = _product_label_en(candidate)
    return _dedupe_queries(_recommended_site_queries(product_zh, product_en, technology_tag))


def _build_general_gap_queries(
    candidate: Candidate, gap_features: list[ClaimFeature]
) -> list[str]:
    """gap round 的通用 query。"""
    product_zh = _product_label(candidate)
    product_en = _product_label_en(candidate)
    queries: list[str] = []
    for feature in gap_features:
        feature_text = feature.feature_text[:100]
        queries.append(f"{product_zh} {feature_text} 证据")
        queries.append(f"{product_zh} {feature_text} 参数")
        if product_en:
            queries.append(f"{product_en} {feature_text}")
            queries.append(f"{product_en} {feature_text} datasheet")
    return _dedupe_queries(queries)[:30]


def _build_site_gap_queries(
    candidate: Candidate,
    gap_features: list[ClaimFeature],
    technology_tag: str | None,
) -> list[str]:
    """gap round 的 site: 限定 query —— 在推荐垂类站点内找缺口 feature 的证据。"""
    product_zh = _product_label(candidate)
    product_en = _product_label_en(candidate)
    out: list[str] = []
    for feature in gap_features:
        out.extend(
            _recommended_site_queries(
                f"{product_zh} {feature.feature_text[:60]}",
                f"{product_en} {feature.feature_text[:60]}" if product_en else "",
                technology_tag,
            )
        )
    return _dedupe_queries(out)[:15]


def _recommended_site_queries(
    product_zh: str,
    product_en: str,
    technology_tag: str | None,
) -> list[str]:
    """按 technology_tag 拼 `<product> site:<host>` query 列表。

    - tag 专属站点（如电池专利 → batteryfinds.com）+ 所有 tag 通用站点（畅易/汽修巴巴）
    - 每个站点最多产出 2 条 query（中文 + 英文，没英文标签时只出中文）
    - tag 为 None 时只跑 universal sites
    """
    if not product_zh and not product_en:
        return []
    sites = get_recommended_sites_for_tag(technology_tag) if technology_tag else ()
    if not sites and technology_tag is None:
        # 退化路径：不传 tag 也至少跑 universal sites
        from patentradar.core.constants import load_universal_sites
        sites = load_universal_sites()
    out: list[str] = []
    for site in sites:
        host = _site_host(site.url)
        if not host:
            continue
        if product_zh:
            out.append(f"{product_zh} site:{host}")
        if product_en:
            out.append(f"{product_en} site:{host}")
    return out


def _site_host(url: str) -> str:
    """从 https://host/path 抽出 host（不带协议、不带路径），供 `site:` 修饰用。"""
    from urllib.parse import urlparse
    return urlparse(url).netloc.strip().lower()


def _fetch_url_list(
    *,
    candidate: Candidate,
    claim_features: list[ClaimFeature],
    urls: list[str],
    max_pages: int,
    technology_tag: str | None = None,
) -> tuple[list[dict[str, str]], list[dict]]:
    """Fetch a hand-picked URL list (e.g. step3 source_urls). Returns
    (text-pages, image-records) tuples; image-records carry per-image source url
    so LLM can attribute each rendered page back to its origin."""
    if not urls or max_pages <= 0:
        return [], []
    keywords = _build_keywords(candidate=candidate, claim_features=claim_features)
    pages: list[dict[str, str]] = []
    images: list[dict] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        evidence = fetch_evidence(url, keywords=keywords, max_chars=6000, technology_tag=technology_tag)
        if evidence is None:
            continue
        if evidence.text:
            pages.append({"url": evidence.url, "title": evidence.title or "", "text": evidence.text[:6000]})
        for img in evidence.images:
            images.append({
                "url": img.src_url,
                "title": img.alt or evidence.title or "",
                "png": img.png,
                "score": img.score,
                "surrounding_text": img.surrounding_text,
            })
        if len(pages) >= max_pages:
            break
    return pages, images


def fetch_relevant_pages(
    *,
    candidate: Candidate,
    claim_features: list[ClaimFeature],
    results: list[SearchResult],
    max_pages: int = 12,
    technology_tag: str | None = None,
) -> tuple[list[dict[str, str]], list[dict]]:
    keywords = _build_keywords(candidate=candidate, claim_features=claim_features)
    pages: list[dict[str, str]] = []
    images: list[dict] = []
    seen_urls: set[str] = set()
    for result in results:
        if result.url in seen_urls:
            continue
        seen_urls.add(result.url)
        evidence = fetch_evidence(result.url, keywords=keywords, max_chars=6000, technology_tag=technology_tag)
        if evidence is None:
            continue
        if evidence.text:
            pages.append(
                {
                    "url": evidence.url,
                    "title": evidence.title or result.title,
                    "text": evidence.text[:6000],
                }
            )
        for img in evidence.images:
            images.append(
                {
                    "url": img.src_url,
                    "title": img.alt or evidence.title or result.title,
                    "png": img.png,
                    "score": img.score,
                    "surrounding_text": img.surrounding_text,
                }
            )
        if len(pages) >= max_pages:
            break
    return pages, images


def merge_contexts(*contexts: CandidateEvidenceContext) -> CandidateEvidenceContext:
    if not contexts:
        raise ValueError("contexts must not be empty")
    candidate = contexts[0].candidate
    queries: list[str] = []
    results: list[SearchResult] = []
    pages: list[dict[str, str]] = []
    images: list[dict] = []
    seen_result_urls: set[str] = set()
    seen_page_urls: set[str] = set()
    seen_image_urls: set[str] = set()
    for context in contexts:
        queries.extend(context.queries)
        for result in context.search_results:
            if result.url in seen_result_urls:
                continue
            seen_result_urls.add(result.url)
            results.append(result)
        for page in context.fetched_pages:
            if page["url"] in seen_page_urls:
                continue
            seen_page_urls.add(page["url"])
            pages.append(page)
        for image in context.fetched_images:
            # Multiple images can come from the same URL (different PDF pages),
            # dedupe on (url, png-bytes) to keep them all.
            key = (image["url"], hash(image["png"]))
            if key in seen_image_urls:
                continue
            seen_image_urls.add(key)
            images.append(image)
    return CandidateEvidenceContext(
        candidate=candidate,
        queries=_dedupe_queries(queries),
        search_results=results,
        fetched_pages=pages,
        fetched_images=images,
    )


def _product_label(candidate: Candidate) -> str:
    pieces = [candidate.company, candidate.product_name, candidate.product_version]
    return " ".join(piece for piece in pieces if piece).strip()


def _product_label_en(candidate: Candidate) -> str:
    """English label for international searches. Returns "" if step3 LLM didn't
    populate company_en/product_name_en, in which case the caller falls back
    to Chinese-only queries."""
    pieces = [candidate.company_en, candidate.product_name_en, candidate.product_version]
    label = " ".join(piece for piece in pieces if piece and piece.strip()).strip()
    return label


def _build_keywords(*, candidate: Candidate, claim_features: list[ClaimFeature]) -> list[str]:
    return [
        candidate.company,
        candidate.product_name,
        candidate.product_version,
        *[feature.feature_text[:24] for feature in claim_features],
    ]


def _dedupe_queries(queries: list[str]) -> list[str]:
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))
