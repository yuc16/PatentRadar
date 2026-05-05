"""Evidence search strategy helpers.

The search layer should maximize recall, but the LLM should see evidence in a
useful order: official/product documents first, secondary reports next, and
low-authority material only as leads.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .schemas import ClaimFeature


_SPACE_RE = re.compile(r"\s+")

_LOW_VALUE_DOMAINS = (
    "patents.google.com",
    "patentscope.wipo.int",
    "xjishu.com",
    "zhuanlichaxun.net",
    "soopat.com",
    "book118.com",
    "docin.com",
    "doc88.com",
    "weixin.qq.com",
    "zhihu.com",
    "csdn.net",
    "taobao.com",
    "tmall.com",
    "jd.com",
    "amazon.",
    "aliexpress.",
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


def normalize_query(query: str) -> str:
    return _SPACE_RE.sub(" ", (query or "").strip().lower())


def domain_of(url: str) -> str:
    return urlparse(url or "").netloc.lower().lstrip("www.")


def source_type_from_url_title(url: str, title: str = "") -> str:
    low = f"{url} {title}".lower()
    title_cn = title or ""
    if ".pdf" in low:
        if any(x in low for x in ("datasheet", "data-sheet", "数据手册", "规格书", "specification")):
            return "产品手册"
        if any(x in low for x in ("whitepaper", "white-paper", "白皮书")):
            return "白皮书"
        return "官方PDF"
    if "cninfo.com.cn" in low or "static.cninfo.com.cn" in low:
        if "招股" in title_cn:
            return "招股书"
        return "年报"
    if any(x in low for x in ("standard", "标准", "iso.", "iec.", "gb/t")):
        return "标准"
    if any(x in low for x in ("cert", "认证", "approval")):
        return "认证资料"
    if any(x in low for x in ("datasheet", "manual", "specification", "product guide", "产品手册", "规格书")):
        return "产品手册"
    if any(x in low for x in ("whitepaper", "白皮书")):
        return "白皮书"
    if any(x in low for x in ("report", "研究报告", "行业报告")):
        return "行业报告"
    if any(x in domain_of(url) for x in ("weixin", "zhihu", "csdn", "blog")):
        return "自媒体"
    if any(x in domain_of(url) for x in ("taobao", "tmall", "jd.com", "amazon", "aliexpress")):
        return "二手转载"
    if any(x in domain_of(url) for x in _NEWS_DOMAINS) or "新闻" in title_cn:
        return "普通新闻"
    if _looks_official_product_page(url):
        return "官网"
    return "其他"


def reliability_from_url_title(url: str, title: str = "") -> str:
    st = source_type_from_url_title(url, title)
    if st in {"官网", "官方PDF", "产品手册", "白皮书", "标准", "认证资料", "年报", "招股书"}:
        return "high"
    if st in {"权威媒体", "行业报告", "研究报告", "普通新闻", "展会报道", "其他"}:
        return "medium"
    return "low"


def tier_rank(url: str, title: str = "") -> int:
    st = source_type_from_url_title(url, title)
    if st in {"官网", "官方PDF", "产品手册", "白皮书", "标准", "认证资料", "年报", "招股书"}:
        return 3
    if st in {"权威媒体", "行业报告", "研究报告", "展会报道"}:
        return 2
    if st in {"普通新闻", "其他"}:
        return 1
    return 0


def tier_label(url: str, title: str = "") -> str:
    rank = tier_rank(url, title)
    if rank >= 3:
        return "Tier 1 官方/高可靠"
    if rank == 2:
        return "Tier 2 行业/权威"
    if rank == 1:
        return "Tier 3 线索资料"
    return "Tier 4 低可靠线索"


def sort_urls_by_value(urls: list[str], titles: dict[str, str]) -> list[str]:
    return sorted(
        dict.fromkeys(urls),
        key=lambda u: (tier_rank(u, titles.get(u, "")), _looks_crawlable_path(u), -len(u)),
        reverse=True,
    )


def is_crawl_worthy(url: str, title: str = "") -> bool:
    low = (url or "").lower()
    if not low or ".pdf" in low:
        return False
    domain = domain_of(url)
    if any(d in domain for d in _LOW_VALUE_DOMAINS):
        return False
    if any(d in domain for d in _NEWS_DOMAINS):
        return False
    return _looks_crawlable_path(url) or source_type_from_url_title(url, title) == "官网"


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


def build_feature_evidence_queries(
    company: str,
    product: str,
    feature: ClaimFeature,
    *,
    include_counter: bool = False,
) -> list[str]:
    base = f"{company} {product}".strip()
    terms = _feature_terms(feature)
    core = " ".join(terms[:5]) or feature.feature_text[:80]
    english_core = " ".join(_english_feature_terms(feature)[:6]) or core
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


def _english_feature_terms(feature: ClaimFeature) -> list[str]:
    text = feature.feature_text.lower()
    terms: list[str] = []

    for term in [*feature.marketing_terms, *feature.engineering_terms]:
        raw = str(term).strip()
        if raw and raw.isascii():
            terms.append(raw)
        else:
            terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9 /+_.-]{1,}", raw))

    keyword_map = [
        (("电芯", "电池单体", "单体电池"), ("battery cell", "cell")),
        (("方壳",), ("prismatic cell",)),
        (("刀片", "短刀", "长条"), ("blade battery", "short blade battery", "long cell")),
        (("长度", "长宽", "厚度", "宽度"), ("cell length", "cell width", "cell thickness")),
        (("壳体", "外壳", "结构", "封装"), ("cell structure", "housing", "package")),
        (("极柱", "极耳", "连接"), ("terminal", "tab", "connection")),
        (("能量密度", "空间利用率", "体积"), ("energy density", "space utilization", "volumetric efficiency")),
        (("安全", "热失控", "散热"), ("safety", "thermal runaway", "thermal management")),
        (("算法", "计算", "校准", "补偿", "系数"), ("algorithm", "calibration", "compensation")),
        (("传感", "检测", "识别"), ("sensor", "detection", "recognition")),
        (("控制", "生成", "提示", "方法", "流程"), ("control method", "generation", "notification")),
    ]
    for needles, mapped in keyword_map:
        if any(n in text for n in needles):
            terms.extend(mapped)

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


def _is_algorithm_feature(feature: ClaimFeature) -> bool:
    text = feature.feature_text.lower()
    return "$" in text or "公式" in text or any(x in text for x in ("算法", "计算", "修正", "校准", "系数"))


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


def _looks_official_product_page(url: str) -> bool:
    return _looks_crawlable_path(url) and tier_rank_by_domain(url) >= 1


def _looks_crawlable_path(url: str) -> bool:
    parsed = urlparse(url or "")
    haystack = f"{parsed.path} {parsed.query}".lower()
    return any(hint in haystack for hint in _CRAWL_PATH_HINTS)


def tier_rank_by_domain(url: str) -> int:
    domain = domain_of(url)
    if not domain or any(d in domain for d in _LOW_VALUE_DOMAINS):
        return 0
    if any(d in domain for d in _NEWS_DOMAINS):
        return 0
    return 1
