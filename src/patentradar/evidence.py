"""Evidence search strategy helpers.

The search layer should maximize recall, but the LLM should see evidence in a
useful order: official/product documents first, secondary reports next, and
low-authority material only as leads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from string import Formatter
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .schemas import ClaimFeature
from .search import cn_industry


_SPACE_RE = re.compile(r"\s+")

_LOW_VALUE_DOMAINS = (
    "patents.google.com",
    "patentscope.wipo.int",
    "xjishu.com",
    "zhuanlichaxun.net",
    "soopat.com",
    "datasheet.eeworld.com.cn",
    "datasheetarchive.com",
    "datasheetq.com",
    "alldatasheet.com",
    "alldatasheet.net",
    "alldatasheetde.com",
    "datasheetcatalog.net",
    "manualslib.com",
    "semiee.com",
    "findic.us",
    "book118.com",
    "max.book118.com",
    "docin.com",
    "doc88.com",
    "taodocs.com",
    "souwenku.com",
    "wendoc.com",
    "scribd.com",
    "weixin.qq.com",
    "zhihu.com",
    "csdn.net",
    "taobao.com",
    "tmall.com",
    "jd.com",
    "1688.com",
    "dhgate.com",
    "made-in-china.com",
    "amazon.",
    "aliexpress.",
)

_PATENT_OR_DOC_DOMAINS = (
    "patents.google.com",
    "patentscope.wipo.int",
    "xjishu.com",
    "zhuanlichaxun.net",
    "soopat.com",
)

_SOCIAL_MEDIA_DOMAINS = (
    "facebook.com",
    "reddit.com",
    "youtube.com",
    "linkedin.com",
)

_LONG_FORM_PDF_DOMAINS = (
    "static.cninfo.com.cn",
    "cninfo.com.cn",
    "static.sse.com.cn",
    "sse.com.cn",
    "notice.10jqka.com.cn",
    "pdf.dfcfw.com",
    "file.iyanbao.com",
    "stockn.xueqiu.com",
    "hkexnews.hk",
    "invest.calb-tech.com",
    "en.invest.calb-tech.com",
    "cnipa.gov.cn",
    "paper.people.com.cn",
    "esg-disclosure.com",
)

_LONG_FORM_PDF_HINTS = (
    "annual report",
    "prospectus",
    "research report",
    "official catalogue",
    "announcement",
    "disclosure/announcement",
    "global offering",
    "证券研究报告",
    "行业研究",
    "公司深度",
    "公告",
    "上市文件",
    "年度报告",
    "年报",
    "招股",
    "招股章程",
    "募集说明书",
    "全球發售",
    "全球发售",
    "聆訊",
    "聆讯",
    "股份有限公司",
    "co., ltd.",
    "可持续发展报告",
    "專利獎",
    "专利奖",
    "获奖项目",
    "參展商名錄",
    "参展商名录",
    "环境、社会及管治",
    "esg",
)

_NEWS_DOMAINS = (
    "news.",
    "36kr.com",
    "sohu.com",
    "sina.com",
    "163.com",
    "qq.com",
    "ifeng.com",
    "thepaper.cn",
)

_CRAWL_PATH_HINTS = (
    "product",
    "products",
    "solution",
    "solutions",
    "support",
    "download",
    "downloads",
    "doc",
    "docs",
    "document",
    "manual",
    "datasheet",
    "sdk",
    "developer",
    "whitepaper",
    "resource",
    "resources",
    "规格",
    "产品",
    "下载",
    "支持",
    "资料",
    "文档",
    "解决方案",
)

_TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "srsltid",
    "fbclid",
    "gclid",
    "yclid",
    "spm",
}

_GENERIC_TERMS = {
    "公司",
    "股份",
    "有限",
    "集团",
    "科技",
    "能源",
    "动力",
    "电子",
    "产品",
    "技术",
    "方案",
    "系统",
    "官网",
    "规格",
    "规格书",
    "手册",
    "datasheet",
    "specification",
    "manual",
    "product",
}

_COMMERCE_DOMAINS = (
    "alibaba.",
    "1688.com",
    "dhgate.com",
    "made-in-china.com",
    "taobao.com",
    "tmall.com",
    "jd.com",
    "amazon.",
    "aliexpress.",
)


@dataclass(frozen=True)
class EvidenceTarget:
    """A focused evidence goal that may support several linked claim features."""

    target_id: str
    label: str
    feature_ids: tuple[str, ...]
    queries: tuple[str, ...]


def normalize_query(query: str) -> str:
    return _SPACE_RE.sub(" ", (query or "").strip().lower())


def domain_of(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower().lstrip("www.")
    except ValueError:
        return ""


def canonicalize_url(url: str) -> str:
    """Normalize URLs for evidence de-duplication without losing semantic query args."""
    raw_url = (url or "").strip()
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return raw_url
    if not parsed.netloc:
        return (url or "").strip()
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        low_key = key.lower()
        if low_key.startswith("utm_") or low_key in _TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, value))
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((
        parsed.scheme.lower() or "https",
        parsed.netloc.lower(),
        path,
        "",
        urlencode(query_items, doseq=True),
        "",
    ))


def source_type_from_url_title(
    url: str,
    title: str = "",
    *,
    industry_tag: str | None = None,
) -> str:
    low = f"{url} {title}".lower()
    title_cn = title or ""
    domain = domain_of(url)
    if any(x in domain for x in _PATENT_OR_DOC_DOMAINS):
        return "专利文献"
    if "cninfo.com.cn" in low or "static.cninfo.com.cn" in low:
        if "招股" in title_cn:
            return "招股书"
        return "年报"
    if ".pdf" in low:
        if any(x in low for x in ("datasheet", "data-sheet", "数据手册", "规格书", "specification")):
            return "产品手册"
        if any(x in low for x in ("whitepaper", "white-paper", "白皮书")):
            return "白皮书"
        return "官方PDF"
    if any(x in low for x in ("standard", "标准", "iso.", "iec.", "gb/t")):
        return "标准"
    if any(x in low for x in ("cert", "认证", "approval")):
        return "认证资料"
    if any(x in low for x in ("datasheet", "manual", "specification", "product guide", "产品手册", "规格书")):
        return "产品手册"
    if _looks_product_spec_page(url, title, industry_tag=industry_tag):
        return "产品手册"
    if any(x in domain for x in _LOW_VALUE_DOMAINS):
        return "二手转载"
    if any(x in low for x in ("whitepaper", "白皮书")):
        return "白皮书"
    if any(x in low for x in ("report", "研究报告", "行业报告")):
        return "行业报告"
    if any(x in domain for x in ("weixin", "zhihu", "csdn", "blog")):
        return "自媒体"
    if any(x in domain for x in ("taobao", "tmall", "jd.com", "amazon", "aliexpress")):
        return "二手转载"
    if any(x in domain for x in _NEWS_DOMAINS) or "新闻" in title_cn:
        return "普通新闻"
    if _looks_official_product_page(url):
        return "官网"
    return "其他"


def reliability_from_url_title(
    url: str,
    title: str = "",
    *,
    industry_tag: str | None = None,
) -> str:
    st = source_type_from_url_title(url, title, industry_tag=industry_tag)
    if st in {"官网", "官方PDF", "产品手册", "白皮书", "标准", "认证资料", "年报", "招股书"}:
        return "high"
    if st in {"权威媒体", "行业报告", "研究报告", "普通新闻", "展会报道", "其他"}:
        return "medium"
    return "low"


def tier_rank(url: str, title: str = "", *, industry_tag: str | None = None) -> int:
    if any(x in domain_of(url) for x in _PATENT_OR_DOC_DOMAINS):
        return 0
    st = source_type_from_url_title(url, title, industry_tag=industry_tag)
    if st == "专利文献":
        return 0
    if st in {"官网", "官方PDF", "产品手册", "白皮书", "标准", "认证资料", "年报", "招股书"}:
        return 3
    if st in {"权威媒体", "行业报告", "研究报告", "展会报道"}:
        return 2
    if st in {"普通新闻", "其他", "自媒体", "论坛", "二手转载"}:
        return 1
    return 0


def tier_label(url: str, title: str = "", *, industry_tag: str | None = None) -> str:
    rank = tier_rank(url, title, industry_tag=industry_tag)
    if rank >= 3:
        return "Tier 1 官方/高可靠"
    if rank == 2:
        return "Tier 2 行业/权威"
    if rank == 1:
        return "Tier 3 线索资料"
    return "Tier 4 低可靠线索"


def sort_urls_by_value(
    urls: list[str],
    titles: dict[str, str],
    *,
    industry_tag: str | None = None,
) -> list[str]:
    return sorted(
        dict.fromkeys(urls),
        key=lambda u: (
            tier_rank(u, titles.get(u, ""), industry_tag=industry_tag),
            _looks_crawlable_path(u),
            -len(u),
        ),
        reverse=True,
    )


def relevance_score(
    url: str,
    title: str,
    snippet: str,
    company: str,
    product: str,
    aliases: list[str] | tuple[str, ...] = (),
    *,
    industry_tag: str | None = None,
) -> int:
    haystack = _SPACE_RE.sub(" ", f"{url} {title} {snippet}".lower())
    score = 0
    company_low = (company or "").lower().strip()
    product_low = (product or "").lower().strip()
    if company_low and company_low in haystack:
        score += 3
    if product_low and product_low in haystack:
        score += 5
    for alias in aliases:
        alias_low = str(alias or "").lower().strip()
        if alias_low and alias_low in haystack:
            score += 3
    for term in _company_variants(company):
        if term in haystack:
            score += 2
    for term in _search_terms(company, industry_tag=industry_tag):
        if term in haystack:
            score += 1
    for term in _search_terms(product, industry_tag=industry_tag):
        if term in haystack:
            score += 3 if any(ch.isdigit() for ch in term) else 2
    for alias in aliases:
        for term in _search_terms(str(alias), industry_tag=industry_tag):
            if term in haystack:
                score += 2
    return score


def product_specificity_score(
    product: str,
    aliases: list[str] | tuple[str, ...] = (),
    *,
    industry_tag: str | None = None,
) -> int:
    """Score whether a candidate name points to a concrete product/model."""
    text = " ".join([product or "", *(str(a) for a in aliases)]).lower()
    score = 0
    if any(hint in text for hint in _industry_strings(industry_tag, "named_product_hints")):
        score += 2
    terms = _search_terms(
        " ".join([product or "", *(str(a) for a in aliases)]),
        industry_tag=industry_tag,
    )
    if any(term.isascii() and term.isalpha() and len(term) >= 4 for term in terms):
        score += 2
    if any(_looks_named_cn_product_term(term, industry_tag=industry_tag) for term in terms):
        score += 2
    if re.search(r"\b[a-z]{1,8}[-_ ]?\d{2,}[a-z0-9-]*\b", text):
        score += 3
    if re.search(r"\b\d{2,4}(?:\.\d+)?\s?ah\b", text):
        score += 1
    numeric_context_terms = _industry_strings(industry_tag, "numeric_model_context_terms")
    if re.search(r"\b\d{3,5}\b", text) and any(hint in text for hint in numeric_context_terms):
        score += 1
    generic_terms = _generic_terms(industry_tag)
    useful_terms = [term for term in terms if term not in generic_terms and len(term) >= 3]
    if len(useful_terms) >= 2:
        score += 1
    return score


def is_relevant_hit(
    url: str,
    title: str,
    snippet: str,
    company: str,
    product: str,
    aliases: list[str] | tuple[str, ...] = (),
    *,
    industry_tag: str | None = None,
) -> bool:
    """Keep evidence leads that mention the target company/product strongly enough."""
    if not company and not product:
        return True
    has_product_signal = not product or _has_product_signal(
        url,
        title,
        snippet,
        product,
        aliases,
        industry_tag=industry_tag,
    )
    score = relevance_score(
        url,
        title,
        snippet,
        company,
        product,
        aliases,
        industry_tag=industry_tag,
    )
    domain = domain_of(url)
    source_type = source_type_from_url_title(url, title, industry_tag=industry_tag)
    public_spec_like = source_type == "产品手册" or _is_industry_spec_seed_domain(
        url,
        industry_tag=industry_tag,
    )
    has_company_signal = _has_company_signal(
        url,
        title,
        snippet,
        company,
        industry_tag=industry_tag,
    )
    if source_type == "专利文献":
        return False
    if public_spec_like and _looks_spec_index_page(url, title, snippet):
        return True
    if public_spec_like and has_product_signal:
        return True
    if public_spec_like and not has_company_signal:
        return False
    if has_company_signal and source_type in {"官网", "官方PDF", "产品手册", "白皮书", "标准", "认证资料", "年报", "招股书"}:
        return True
    if has_product_signal:
        return score >= 2
    if source_type in {"官网", "官方PDF", "产品手册", "白皮书", "标准", "认证资料", "年报", "招股书"}:
        return score >= 2
    if product_specificity_score(product, aliases, industry_tag=industry_tag) < 2:
        return score >= 4
    if any(d in domain for d in _LOW_VALUE_DOMAINS):
        return score >= 5
    return score >= 3


def should_read_url(url: str, title: str = "", *, industry_tag: str | None = None) -> bool:
    """Whether a URL is worth paid/full-text extraction."""
    domain = domain_of(url)
    if not url:
        return False
    if any(d in domain for d in _PATENT_OR_DOC_DOMAINS):
        return False
    if any(d in domain for d in _SOCIAL_MEDIA_DOMAINS):
        return False
    if is_long_form_pdf(url, title, industry_tag=industry_tag):
        return False
    st = source_type_from_url_title(url, title, industry_tag=industry_tag)
    return st != "专利文献"


def is_spec_index_page(url: str, title: str = "", snippet: str = "") -> bool:
    return _looks_spec_index_page(url, title, snippet)


def is_long_form_pdf(url: str, title: str = "", *, industry_tag: str | None = None) -> bool:
    low = f"{url} {title}".lower()
    if ".pdf" not in low:
        return False
    if source_type_from_url_title(url, title, industry_tag=industry_tag) == "产品手册":
        return False
    domain = domain_of(url)
    if any(d in domain for d in _LONG_FORM_PDF_DOMAINS):
        return True
    return any(hint in low for hint in _LONG_FORM_PDF_HINTS)


def is_crawl_worthy(url: str, title: str = "", *, industry_tag: str | None = None) -> bool:
    low = (url or "").lower()
    if not low or ".pdf" in low:
        return False
    domain = domain_of(url)
    if any(d in domain for d in _LOW_VALUE_DOMAINS):
        return False
    if any(d in domain for d in _COMMERCE_DOMAINS):
        return False
    if any(d in domain for d in _NEWS_DOMAINS):
        return False
    st = source_type_from_url_title(url, title, industry_tag=industry_tag)
    return st == "官网" or (
        st == "产品手册"
        and any(hint in low for hint in ("download", "downloads", "datasheet", "specification", "规格"))
    )


def build_general_evidence_queries(company: str, product: str) -> list[str]:
    base = f"{company} {product}".strip()
    return _dedupe_queries([
        base,
        f"{base} 官网 产品手册 规格书 datasheet",
        f"{base} datasheet specification product manual white paper",
        f"{base} filetype:pdf datasheet 规格书 产品手册",
        f"{base} 白皮书 技术文档 SDK 拆解 结构图",
        f"{base} technical document SDK teardown structure",
    ])


def build_evidence_targets(
    company: str,
    product: str,
    features: list[ClaimFeature],
    *,
    aliases: list[str] | tuple[str, ...] = (),
    industry_tag: str | None = None,
    include_counter: bool = False,
) -> list[EvidenceTarget]:
    """Generate bilingual evidence goals for a candidate product.

    One datasheet or product page often supports several features at once
    (dimensions, capacity, structure, parameters).  Targets therefore group
    related features before query generation instead of searching Fi one by one.
    """
    base = f"{company} {product}".strip()
    if not base:
        return []

    feature_ids = tuple(f.feature_id for f in features if f.feature_id)
    targets: list[EvidenceTarget] = []

    def add_target(
        target_id: str,
        label: str,
        ids: list[str] | tuple[str, ...],
        queries: list[str],
    ) -> None:
        deduped = tuple(_dedupe_queries(queries))
        if not deduped:
            return
        targets.append(EvidenceTarget(
            target_id=target_id,
            label=label,
            feature_ids=tuple(dict.fromkeys(ids)),
            queries=deduped,
        ))

    spec_ids = _feature_ids_by_predicate(features, _is_spec_or_parameter_feature)
    industry_spec_queries = _industry_query_templates(industry_tag, "spec_queries", base=base)
    if spec_ids or industry_spec_queries:
        spec_queries = []
        for alias_base in _alias_query_bases(company, product, aliases, industry_tag=industry_tag):
            spec_queries.extend([
                f"{alias_base} energy capacity voltage dimension datasheet specification",
                f"{alias_base} 能量 容量 电压 尺寸 规格书 参数",
                f"{alias_base} dimensions size length width thickness datasheet specification",
                f"{alias_base} 规格书 尺寸 长度 宽度 厚度 电芯",
                f"{alias_base} Dimension mm battery cell product specification",
            ])
        spec_queries.extend([
            f"{base} energy capacity voltage dimension datasheet specification",
            f"{base} 能量 容量 电压 尺寸 规格书 参数",
            f"{base} 规格 参数 规格书 产品手册 datasheet PDF",
            f"{base} datasheet specification product manual parameters pdf",
            f"{base} filetype:pdf datasheet specification 规格书 产品手册",
            f"{base} 经销商 代理商 供应商 规格 参数 产品手册",
            f"{base} distributor supplier dealer product specification datasheet",
        ])
        spec_queries.extend(industry_spec_queries)
        add_target("spec", "规格/参数/手册证据", spec_ids or list(feature_ids), spec_queries)
    else:
        add_target("product_docs", "产品/技术资料证据", feature_ids, [
            f"{base} 官网 产品 技术资料 白皮书 说明",
            f"{base} product page technical document white paper solution",
            f"{base} 技术方案 使用说明 SDK API 案例",
            f"{base} documentation guide case study product description",
        ])

    structure_ids = _feature_ids_by_predicate(
        features,
        lambda feature: _is_structure_feature(feature, industry_tag=industry_tag),
    )
    if structure_ids:
        add_target("structure", "结构/形态/连接证据", structure_ids, [
            f"{base} 结构 外形 连接 壳体 拆解 图示 规格书",
            f"{base} structure housing package connection teardown diagram",
            f"{base} 产品页 结构图 技术资料 white paper",
            f"{base} technical document structure diagram product page",
            *[
                f"{alias_base} blade prismatic cell dimension drawing structure"
                for alias_base in _alias_query_bases(company, product, aliases, industry_tag=industry_tag)[:3]
            ],
        ])

    algorithm_ids = _feature_ids_by_predicate(features, _is_algorithm_feature)
    if algorithm_ids:
        add_target("algorithm", "算法/控制/流程证据", algorithm_ids, [
            f"{base} 算法 控制 方法 SDK API 白皮书 技术文档",
            f"{base} algorithm control method SDK API white paper technical document",
            f"{base} calibration compensation workflow developer documentation",
            f"{base} 技术方案 说明书 软件 算法 校准 补偿",
        ])

    covered = {fid for t in targets for fid in t.feature_ids}
    for feature in features:
        if feature.feature_id in covered:
            continue
        add_target(
            f"feature_{feature.feature_id}",
            f"{feature.feature_id} 定向证据",
            [feature.feature_id],
            build_feature_evidence_queries(
                company,
                product,
                feature,
                industry_tag=industry_tag,
                include_counter=include_counter,
            ),
        )

    add_target("market_date", "上市/发布/量产日期证据", (), [
        f"{base} 上市 发布时间 发布 量产 首发",
        f"{base} launch release mass production announced availability",
        f"{base} product launch date released supplier catalog",
    ])

    if include_counter and feature_ids:
        add_target("counter", "反证/差异证据", feature_ids, [
            f"{base} difference limitation not support conflict principle 反证 不支持 差异",
            f"{base} review teardown comparison limitation 缺陷 不同 技术路线",
        ])

    return _dedupe_targets(targets)


def build_feature_evidence_queries(
    company: str,
    product: str,
    feature: ClaimFeature,
    *,
    industry_tag: str | None = None,
    include_counter: bool = False,
) -> list[str]:
    base = f"{company} {product}".strip()
    terms = _feature_terms(feature)
    core = " ".join(terms[:5]) or feature.feature_text[:80]
    english_core = " ".join(_english_feature_terms(feature, industry_tag=industry_tag)[:6]) or core
    suffix = _feature_suffix(feature)
    queries = [
        f"{base} {core} {suffix}",
        f"{base} {english_core} datasheet specification technical document",
        f"{base} {core} {english_core} filetype:pdf",
        f"{base} {core} 官网 产品手册 白皮书 技术文档",
    ]
    if _is_algorithm_feature(feature):
        queries.append(
            f"{base} {core} {english_core} SDK API algorithm calibration compensation 校准 补偿"
        )
    if include_counter:
        queries.append(
            f"{base} {core} {english_core} 反证 不支持 difference principle conflict"
        )
    return _dedupe_queries(queries)


def _feature_terms(feature: ClaimFeature) -> list[str]:
    terms: list[str] = []
    terms.extend(feature.marketing_terms[:3])
    terms.extend(feature.engineering_terms[:4])
    if _is_algorithm_feature(feature):
        terms.extend(["算法", "SDK", "校准", "补偿"])
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        t = str(term).strip()
        if t and t not in seen:
            out.append(t)
            seen.add(t)
    return out


def _english_feature_terms(feature: ClaimFeature, *, industry_tag: str | None = None) -> list[str]:
    text = feature.feature_text.lower()
    terms: list[str] = []

    for term in [*feature.marketing_terms, *feature.engineering_terms]:
        raw = str(term).strip()
        if raw and raw.isascii():
            terms.append(raw)
        else:
            terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9 /+_.-]{1,}", raw))

    keyword_map = [
        (("长度", "长宽", "厚度", "宽度", "尺寸"), ("length", "width", "thickness", "dimensions")),
        (("壳体", "外壳", "结构", "封装"), ("structure", "housing", "package")),
        (("连接", "安装", "布置"), ("connection", "mounting", "layout")),
        (("体积", "容量", "电压", "电流", "密度"), ("volume", "capacity", "voltage", "current", "density")),
        (("算法", "计算", "校准", "补偿", "系数"), ("algorithm", "calibration", "compensation")),
        (("传感", "检测", "识别"), ("sensor", "detection", "recognition")),
        (("控制", "生成", "提示", "方法", "流程"), ("control method", "generation", "notification")),
    ]
    for needles, mapped in keyword_map:
        if any(n in text for n in needles):
            terms.extend(mapped)
    for item in _industry_feature_term_map(industry_tag):
        needles = tuple(item.get("needles") or ())
        mapped = tuple(item.get("terms") or ())
        if needles and mapped and any(str(n) in text for n in needles):
            terms.extend(str(t) for t in mapped if str(t).strip())

    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        clean = _SPACE_RE.sub(" ", term).strip()
        key = clean.lower()
        if clean and key not in seen:
            out.append(clean)
            seen.add(key)
    return out


def _feature_suffix(feature: ClaimFeature) -> str:
    text = feature.feature_text
    if _is_algorithm_feature(feature):
        return "白皮书 技术文档 API 说明"
    if any(x in text for x in ("方法", "步骤", "流程", "根据", "计算", "生成")):
        return "技术方案 白皮书 SDK API 说明书"
    if any(x in text for x in ("层", "板", "芯片", "连接", "材料", "涂", "封装", "结构")):
        return "结构图 拆解 规格书 产品手册 datasheet"
    return "规格书 产品手册 白皮书 技术资料"


def _feature_ids_by_predicate(
    features: list[ClaimFeature],
    predicate,
) -> list[str]:
    return [f.feature_id for f in features if f.feature_id and predicate(f)]


def _is_spec_or_parameter_feature(feature: ClaimFeature) -> bool:
    text = _feature_text_with_terms(feature)
    return bool(re.search(r"\d", text)) or any(
        x in text
        for x in (
            "长度", "宽度", "厚度", "高度", "尺寸", "长宽", "比例", "表面积",
            "体积", "容量", "电压", "电流", "能量", "密度", "质量", "重量",
            "参数", "规格", "diameter", "length", "width", "height", "thickness",
            "dimension", "capacity", "voltage", "current", "density", "volume",
        )
    )


def _is_structure_feature(feature: ClaimFeature, *, industry_tag: str | None = None) -> bool:
    text = _feature_text_with_terms(feature)
    generic_hit = any(
        x in text
        for x in (
            "结构", "壳体", "外壳", "封装", "连接", "层叠", "叠置",
            "长方体", "矩形", "安装", "布置",
            "structure", "housing", "package", "connection", "rectangular",
        )
    )
    if generic_hit:
        return True
    return any(hint in text for hint in _industry_strings(industry_tag, "structure_feature_hints"))


def _is_algorithm_feature(feature: ClaimFeature) -> bool:
    text = _feature_text_with_terms(feature)
    return "$" in text or "公式" in text or any(x in text for x in ("算法", "计算", "修正", "校准", "系数"))


def _feature_text_with_terms(feature: ClaimFeature) -> str:
    return " ".join(
        [feature.feature_text, *feature.marketing_terms, *feature.engineering_terms]
    ).lower()


def _dedupe_targets(targets: list[EvidenceTarget]) -> list[EvidenceTarget]:
    out: list[EvidenceTarget] = []
    seen_ids: set[str] = set()
    seen_queries: set[str] = set()
    for target in targets:
        if target.target_id in seen_ids:
            continue
        queries: list[str] = []
        for query in target.queries:
            key = normalize_query(query)
            if key and key not in seen_queries:
                seen_queries.add(key)
                queries.append(query)
        if queries:
            out.append(EvidenceTarget(
                target_id=target.target_id,
                label=target.label,
                feature_ids=target.feature_ids,
                queries=tuple(queries),
            ))
            seen_ids.add(target.target_id)
    return out


def _dedupe_queries(queries: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        clean = _SPACE_RE.sub(" ", q).strip()
        key = normalize_query(clean)
        if clean and key not in seen:
            out.append(clean)
            seen.add(key)
    return out


def _alias_query_bases(
    company: str,
    product: str,
    aliases: list[str] | tuple[str, ...],
    *,
    industry_tag: str | None = None,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    company_terms = [company, *_industry_company_aliases(company, industry_tag=industry_tag)]
    candidate_aliases = []
    for alias in aliases:
        text = str(alias or "").strip()
        if not text:
            continue
        low = text.lower()
        if any(ch.isdigit() for ch in text) or any(h in low for h in _industry_strings(industry_tag, "named_product_hints")):
            candidate_aliases.append(text)
    if not candidate_aliases and product:
        candidate_aliases.append(product)
    candidate_aliases = sorted(
        dict.fromkeys(candidate_aliases),
        key=lambda s: (0 if re.search(r"(?i)\b\d{2,4}\s?ah\b", s) else 1, len(s)),
    )
    for alias in candidate_aliases[:5]:
        for comp in company_terms[:3]:
            base = f"{comp} {alias}".strip()
            key = normalize_query(base)
            if base and key not in seen:
                out.append(base)
                seen.add(key)
    return out[:8]


def _looks_official_product_page(url: str) -> bool:
    return _looks_crawlable_path(url) and tier_rank_by_domain(url) >= 1


def _looks_product_spec_page(
    url: str,
    title: str = "",
    *,
    industry_tag: str | None = None,
) -> bool:
    low = f"{url} {title}".lower()
    if any(
        hint in low
        for hint in (
            "datasheet",
            "data-sheet",
            "specification",
            "product manual",
            "manual",
            "capacity",
            "voltage",
            "dimension",
            "规格书",
            "产品手册",
            "参数",
            "容量",
            "电压",
            "尺寸",
        )
    ):
        return True
    industry_hints = _industry_strings(industry_tag, "product_spec_page_hints")
    if industry_hints and any(hint in low for hint in industry_hints):
        return True
    context_terms = _industry_strings(industry_tag, "product_spec_context_terms")
    if re.search(r"\b\d{2,4}(?:\.\d+)?\s?ah\b", low) and any(
        token in low
        for token in context_terms
    ):
        return True
    return False


def _looks_spec_index_page(url: str, title: str = "", snippet: str = "") -> bool:
    low = f"{url} {title} {snippet}".lower()
    return any(
        hint in low
        for hint in (
            "datasheet list",
            "download",
            "downloads",
            "specification pdf",
            "product specification pdf",
            "battery-cell-datasheet-list",
            "download/",
            "规格书列表",
            "资料下载",
            "下载",
        )
    )


def _looks_crawlable_path(url: str) -> bool:
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    haystack = f"{parsed.path} {parsed.query}".lower()
    return any(hint in haystack for hint in _CRAWL_PATH_HINTS)


def tier_rank_by_domain(url: str) -> int:
    domain = domain_of(url)
    if not domain or any(d in domain for d in _LOW_VALUE_DOMAINS):
        return 0
    if any(d in domain for d in _NEWS_DOMAINS):
        return 0
    return 1


def _industry_profile(industry_tag: str | None) -> dict:
    if not industry_tag:
        return {}
    return cn_industry.load_evidence_profile(industry_tag)


def _industry_strings(industry_tag: str | None, key: str) -> tuple[str, ...]:
    raw = _industry_profile(industry_tag).get(key) or []
    if not isinstance(raw, list):
        return ()
    return tuple(
        str(item).strip().lower()
        for item in raw
        if str(item).strip()
    )


def _all_industry_strings(key: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for tag in cn_industry.known_tags():
        for item in _industry_strings(tag, key):
            if item not in seen:
                out.append(item)
                seen.add(item)
    return tuple(out)


def _industry_feature_term_map(industry_tag: str | None) -> list[dict]:
    raw = _industry_profile(industry_tag).get("feature_term_map") or []
    return [item for item in raw if isinstance(item, dict)]


def _industry_query_templates(industry_tag: str | None, key: str, **values: str) -> list[str]:
    raw = _industry_profile(industry_tag).get(key) or []
    out: list[str] = []
    for template in raw:
        if not isinstance(template, str) or not template.strip():
            continue
        try:
            fields = {name for _, name, _, _ in Formatter().parse(template) if name}
            context = {field: values.get(field, "") for field in fields}
            out.append(template.format(**context))
        except (KeyError, ValueError):
            continue
    return out


def _generic_terms(industry_tag: str | None = None) -> set[str]:
    return set(_GENERIC_TERMS) | set(_industry_strings(industry_tag, "generic_terms"))


def _search_terms(text: str, *, industry_tag: str | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    generic_terms = _generic_terms(industry_tag)
    for raw in re.findall(r"[a-z0-9][a-z0-9+_.-]{1,}", (text or "").lower()):
        if raw not in generic_terms and raw not in seen:
            out.append(raw)
            seen.add(raw)
    for raw in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
        if raw not in generic_terms and raw not in seen:
            out.append(raw)
            seen.add(raw)
    return out


def _looks_named_cn_product_term(term: str, *, industry_tag: str | None = None) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fff]{4,}", term or ""):
        return False
    generic_suffixes = (
        "系统",
        "产品",
        "方案",
        "技术",
        "平台",
        "模块",
        "组件",
    )
    industry_suffixes = tuple(
        suffix for suffix in _all_industry_strings("generic_terms")
        if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", suffix)
    )
    return not any(term.endswith(suffix) for suffix in (*generic_suffixes, *industry_suffixes))


def _has_product_signal(
    url: str,
    title: str,
    snippet: str,
    product: str,
    aliases: list[str] | tuple[str, ...] = (),
    *,
    industry_tag: str | None = None,
) -> bool:
    haystack = _SPACE_RE.sub(" ", f"{url} {title} {snippet}".lower())
    product_low = (product or "").lower().strip()
    if product_low and product_low in haystack:
        return True
    for alias in aliases:
        alias_low = str(alias or "").lower().strip()
        if alias_low and alias_low in haystack:
            return True
    strong_terms = [
        term for term in _search_terms(product, industry_tag=industry_tag)
        if any(ch.isdigit() for ch in term) or len(term) >= 4
    ]
    for alias in aliases:
        strong_terms.extend(
            term for term in _search_terms(str(alias), industry_tag=industry_tag)
            if any(ch.isdigit() for ch in term) or len(term) >= 4
        )
    if any(term in haystack for term in strong_terms):
        return True

    candidate_text = _SPACE_RE.sub(" ", f"{product} {' '.join(str(a) for a in aliases)}".lower())
    named_hints = _industry_strings(industry_tag, "named_product_hints")
    candidate_has_named_hint = any(hint in candidate_text for hint in named_hints)
    page_has_named_hint = any(hint in haystack for hint in named_hints)
    return candidate_has_named_hint and page_has_named_hint


def _is_industry_spec_seed_domain(url: str, *, industry_tag: str | None = None) -> bool:
    domain = domain_of(url)
    if not domain:
        return False
    for site in cn_industry.load_sites(industry_tag):
        site_domain = (site.domain or "").lower().lstrip("www.")
        if not site_domain:
            continue
        if domain == site_domain or domain.endswith(f".{site_domain}") or site_domain.endswith(f".{domain}"):
            site_type = (site.type or "").lower()
            return any(
                hint in site_type
                for hint in ("规格", "经销商", "供应商", "pdf", "产品手册", "datasheet", "spec")
            )
    return False


def _company_variants(text: str) -> list[str]:
    clean = re.sub(r"\s+", "", text or "")
    if not clean:
        return []
    variants = {clean.lower()}
    stripped = clean
    for suffix in (
        "股份有限公司",
        "有限责任公司",
        "有限公司",
        "股份",
        "集团",
        "科技",
        "能源",
        "动力",
        "电子",
        "公司",
    ):
        if stripped.endswith(suffix) and len(stripped) > len(suffix) + 1:
            stripped = stripped[: -len(suffix)]
            variants.add(stripped.lower())
    if len(stripped) >= 4:
        variants.add(stripped[:4].lower())
    return [v for v in variants if v and v not in _GENERIC_TERMS]


def _has_company_signal(
    url: str,
    title: str,
    snippet: str,
    company: str,
    *,
    industry_tag: str | None = None,
) -> bool:
    haystack = _SPACE_RE.sub(" ", f"{url} {title} {snippet}".lower())
    for term in _company_variants(company):
        if term and term in haystack:
            return True
    for term in _industry_company_aliases(company, industry_tag=industry_tag):
        if term and term in haystack:
            return True
    return False


def _industry_company_aliases(company: str, *, industry_tag: str | None = None) -> list[str]:
    raw = _industry_profile(industry_tag).get("company_aliases") or {}
    if not isinstance(raw, dict):
        return []
    normalized = re.sub(r"\s+", "", company or "").lower()
    if not normalized:
        return []
    out: list[str] = []
    for key, values in raw.items():
        key_norm = re.sub(r"\s+", "", str(key or "")).lower()
        if not key_norm or key_norm not in normalized:
            continue
        if isinstance(values, list):
            out.extend(str(v).strip().lower() for v in values if str(v).strip())
    return out
