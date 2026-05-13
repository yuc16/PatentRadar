"""Evidence search context builder for step 4."""

from __future__ import annotations

from dataclasses import dataclass, field

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
) -> CandidateEvidenceContext:
    # Step 3 already vetted source_urls against claim 1 — fetch them first as
    # high-priority seed evidence before spending search-API budget.
    seed_pages, seed_images = _fetch_url_list(
        candidate=candidate,
        claim_features=claim_features,
        urls=list(candidate.source_urls),
        max_pages=10,
    )
    queries = build_initial_evidence_queries(candidate=candidate, claim_features=claim_features)
    results = router.search_queries(
        publication_no=publication_no,
        queries=queries,
        query_id_prefix=f"{candidate.candidate_id}-I",
        max_results_per_query=5,
        self_signals=self_signals,
    ).results
    seed_urls = {page["url"] for page in seed_pages}
    extra_pages, extra_images = fetch_relevant_pages(
        candidate=candidate,
        claim_features=claim_features,
        results=[r for r in results if r.url not in seed_urls],
        max_pages=max(0, 12 - len(seed_pages)),
    )
    pages = seed_pages + extra_pages
    images = seed_images + extra_images
    return CandidateEvidenceContext(
        candidate=candidate,
        queries=queries,
        search_results=results,
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
) -> CandidateEvidenceContext:
    queries = build_gap_evidence_queries(candidate=candidate, gap_features=gap_features)
    results = router.search_queries(
        publication_no=publication_no,
        queries=queries,
        query_id_prefix=f"{candidate.candidate_id}-G",
        max_results_per_query=5,
        self_signals=self_signals,
    ).results
    pages, images = fetch_relevant_pages(
        candidate=candidate, claim_features=gap_features, results=results
    )
    return CandidateEvidenceContext(
        candidate=candidate,
        queries=queries,
        search_results=results,
        fetched_pages=pages,
        fetched_images=images,
    )


def build_initial_evidence_queries(*, candidate: Candidate, claim_features: list[ClaimFeature]) -> list[str]:
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


def build_gap_evidence_queries(*, candidate: Candidate, gap_features: list[ClaimFeature]) -> list[str]:
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


def _fetch_url_list(
    *,
    candidate: Candidate,
    claim_features: list[ClaimFeature],
    urls: list[str],
    max_pages: int,
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
        evidence = fetch_evidence(url, keywords=keywords, max_chars=6000)
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
) -> tuple[list[dict[str, str]], list[dict]]:
    keywords = _build_keywords(candidate=candidate, claim_features=claim_features)
    pages: list[dict[str, str]] = []
    images: list[dict] = []
    seen_urls: set[str] = set()
    for result in results:
        if result.url in seen_urls:
            continue
        seen_urls.add(result.url)
        evidence = fetch_evidence(result.url, keywords=keywords, max_chars=6000)
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
