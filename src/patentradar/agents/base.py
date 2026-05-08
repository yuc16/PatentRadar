"""SearchAgent 工作流（PRD §8.1 S0~S10）。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from .. import compactor, evidence as evidence_strategy, prompts, scoring
from ..config import AGENT_LLM_TIMEOUT
from ..dates import is_after_application, normalize_date_string
from ..llm.client import chat_json
from ..schemas import (
    AgentOutput,
    Candidate,
    DiscardedCandidate,
    Evidence,
    FeatureMatch,
    QueryRecord,
    TaskPackage,
)
from ..search import cn_industry, cninfo, pool
from ..search.base import ExtractedPage, SearchError, SearchHit
from ..search.session import SearchSession
from .perspectives import AgentPerspective

logger = logging.getLogger("patentradar.agent")


# 候选发现保持宽召回；证据阶段按“核心证据 → 缺口证据”递进，避免低信号候选盲扫。
MIN_QUERIES = 5
MAX_QUERIES = 10
MAX_HITS_PER_ENGINE = 8
COARSE_POOL_LIMIT = 50
FOCUS_POOL_LIMIT = 8
SECOND_FOCUS_POOL_LIMIT = 5
EVIDENCE_READ_URL_LIMIT = 5
EVIDENCE_PAGE_LIMIT = 9
EVIDENCE_URL_POOL_LIMIT = 24
EVIDENCE_HITS_PER_QUERY = 3
EVIDENCE_TARGET_LIMIT = 2
EVIDENCE_QUERIES_PER_TARGET = 2
MARKET_DATE_QUERIES_PER_CANDIDATE = 2
GAP_EVIDENCE_TARGET_LIMIT = 2
GAP_EVIDENCE_QUERIES_PER_TARGET = 2
GAP_FEATURE_SUPPLEMENT_LIMIT = 5
INDUSTRY_SITE_EVIDENCE_QUERY_LIMIT = 2
CRAWL_TARGETS_PER_CANDIDATE = 1
CRAWL_PAGES_PER_TARGET = 2
SECOND_SEARCH_MIN_VALID = 3
SECOND_SEARCH_STOP_SCORE = 90.0
SECOND_SEARCH_TRIGGER_SCORE = 80.0
MIN_INITIAL_SCORE_FOR_GAP = 55.0
MIN_INITIAL_POSITIVE_FEATURES_FOR_GAP = 2
TOP_K = 5

# 中国行业路由：每条原 query 衍生出 site: 限定 query 的最大数（媒体组 + 厂商组）
CN_INDUSTRY_DERIVED_QUERIES = 2
# 巨潮资讯证据补搜上限（每个候选最多取 N 篇公告）
CNINFO_HITS_PER_CANDIDATE = 2

# Pydantic Literal 严格枚举；LLM 自由输出常见的非枚举别名，这里做归一化映射
VALID_SOURCE_TYPES = {
    "官网", "官方PDF", "产品手册", "白皮书", "新闻稿",
    "专利文献", "标准", "认证资料", "年报", "招股书",
    "权威媒体", "行业报告", "研究报告", "普通新闻", "展会报道",
    "自媒体", "论坛", "二手转载", "其他",
}
SOURCE_TYPE_ALIAS = {
    # 中文常见别名
    "专利": "专利文献", "专利公开": "专利文献", "patent": "专利文献",
    "博客": "自媒体", "blog": "自媒体", "微信公众号": "自媒体",
    "百度百科": "权威媒体", "维基百科": "权威媒体", "wiki": "权威媒体",
    "新闻": "普通新闻", "media": "权威媒体",
    "产品页": "官网", "official": "官网", "homepage": "官网",
    "数据手册": "产品手册", "datasheet": "产品手册",
    "招股说明书": "招股书", "招股": "招股书",
    "学术": "研究报告", "论文": "研究报告", "paper": "研究报告",
    "报告": "行业报告", "research": "研究报告",
    "知乎": "自媒体", "csdn": "自媒体", "公众号": "自媒体",
    "电商": "二手转载", "京东": "二手转载", "淘宝": "二手转载",
}
VALID_RELIABILITIES = {"high", "medium", "low"}


@dataclass(frozen=True)
class EvidenceBudget:
    read_url_limit: int = EVIDENCE_READ_URL_LIMIT
    page_limit: int = EVIDENCE_PAGE_LIMIT
    url_pool_limit: int = EVIDENCE_URL_POOL_LIMIT
    crawl_targets: int = CRAWL_TARGETS_PER_CANDIDATE
    crawl_pages: int = CRAWL_PAGES_PER_TARGET
    hits_per_query: int = EVIDENCE_HITS_PER_QUERY


def _normalize_source_type(s: str | None) -> str:
    raw = (s or "").strip()
    if raw in VALID_SOURCE_TYPES:
        return raw
    return SOURCE_TYPE_ALIAS.get(raw.lower(), "其他")


def _normalize_reliability(s: str | None) -> str:
    raw = (s or "").strip().lower()
    if raw in VALID_RELIABILITIES:
        return raw
    if raw in {"高", "high level", "trusted"}:
        return "high"
    if raw in {"低", "low level", "untrusted"}:
        return "low"
    return "medium"


class SearchAgent:
    def __init__(self, perspective: AgentPerspective, search_session: SearchSession | None = None):
        self.persp = perspective
        self.search_session = search_session or SearchSession()
        if not perspective.llm_endpoint.is_configured:
            raise RuntimeError(
                f"Agent {perspective.name} 的 LLM 端点未完整配置 (api_key/base_url/model)"
            )

    @property
    def tag(self) -> str:
        return f"[{self.persp.name}]"

    # ----------- 主入口 -----------
    def run(self, task: TaskPackage) -> AgentOutput:
        t0 = time.monotonic()
        queries_used: list[QueryRecord] = []

        logger.info(
            "%s START patent=%s perspective=%s model=%s",
            self.tag, task.patent.publication_no,
            self.persp.perspective_label, self.persp.llm_endpoint.model,
        )

        # ---------- S1: 生成候选发现 query ----------
        logger.info("%s S1 生成候选发现 query …", self.tag)
        queries = self._gen_queries(task)
        for i, q in enumerate(queries, start=1):
            logger.info("%s   query[%d]: %s", self.tag, i, q)

        # ---------- S2-S3: 主搜索源召回粗候选 ----------
        logger.info(
            "%s S2-S3 主搜索源 [%s] 召回粗候选 …",
            self.tag, "+".join(self.persp.primary_engines),
        )
        coarse_hits = self._search_candidates(task, queries, queries_used)
        logger.info("%s   粗候选池: %d 条 unique URL", self.tag, len(coarse_hits))

        # ---------- S4-S5: 归一化 + 初筛 → 重点候选 ----------
        logger.info("%s S4-S5 LLM 归一化 + 初筛 …", self.tag)
        candidate_decisions = self._filter_candidates(task, coarse_hits)
        focus_candidates = (candidate_decisions.get("candidates") or [])[:FOCUS_POOL_LIMIT]
        discarded: list[DiscardedCandidate] = [
            DiscardedCandidate(**d)
            for d in candidate_decisions.get("discarded_candidates", [])
        ]
        logger.info(
            "%s   保留重点候选 %d，初步丢弃 %d",
            self.tag, len(focus_candidates), len(discarded),
        )
        for i, c in enumerate(focus_candidates, start=1):
            logger.info(
                "%s   focus[%d] %s / %s  aliases=%s",
                self.tag, i, c.get("company"), c.get("product"),
                c.get("aliases") or [],
            )

        # ---------- S6-S7: 每个候选 → 收集证据 + 特征匹配 ----------
        scored: list[Candidate] = []
        attempted_labels: set[str] = set()

        def _evaluate_focus_list(
            focus_list: list[dict[str, Any]],
            stage: str,
            *,
            stop_when_valid: int | None = None,
        ) -> None:
            for idx, c in enumerate(focus_list, start=1):
                if stop_when_valid is not None and len(scored) >= stop_when_valid:
                    logger.info(
                        "%s   %s 已补足有效候选 %d/%d，停止继续二轮处理",
                        self.tag, stage, len(scored), stop_when_valid,
                    )
                    return
                label = f"{c.get('company')}/{c.get('product')}"
                label_key = label.lower().strip()
                if label_key in attempted_labels:
                    continue
                attempted_labels.add(label_key)
                admission_failure = self._candidate_admission_failure(c, task)
                if admission_failure:
                    logger.info("%s   %s 预排除: %s", self.tag, label, admission_failure)
                    discarded.append(DiscardedCandidate(
                        company=c.get("company", ""),
                        product=c.get("product", ""),
                        discard_reason=admission_failure,
                        evidence_urls=[
                            e.get("url", "") for e in (c.get("initial_evidence") or [])
                            if isinstance(e, dict) and e.get("url")
                        ],
                    ))
                    continue
                logger.info(
                    "%s S6-S7 %s [%d/%d] 处理候选 %s",
                    self.tag, stage, idx, len(focus_list), label,
                )
                try:
                    cand = self._evaluate_candidate(task, c, queries_used)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s   evaluate %s 失败: %s", self.tag, label, exc)
                    discarded.append(DiscardedCandidate(
                        company=c.get("company", ""),
                        product=c.get("product", ""),
                        discard_reason=f"特征匹配阶段失败: {exc}",
                    ))
                    continue
                ok, reason = scoring.passes_hard_rules(cand.hard_rule_check)
                if not ok:
                    logger.info("%s   %s 未过硬规则: %s", self.tag, label, reason)
                    discarded.append(DiscardedCandidate(
                        company=cand.company,
                        product=cand.product,
                        discard_reason=reason or "未通过硬性规则",
                        evidence_urls=cand.main_evidence_urls,
                    ))
                    continue
                n_match = sum(
                    1 for fm in cand.feature_match_table
                    if fm.judgement in ("明确满足", "可能满足")
                )
                logger.info(
                    "%s   %s 通过 → score=%.1f, 命中 %d/%d 特征",
                    self.tag, label, cand.score, n_match, len(cand.feature_match_table),
                )
                scored.append(cand)
                best_score = max((item.score for item in scored), default=0.0)
                if (
                    stop_when_valid is not None
                    and (len(scored) >= stop_when_valid or best_score >= SECOND_SEARCH_STOP_SCORE)
                ):
                    logger.info(
                        "%s   %s 已达到停止条件 valid=%d/%d best=%.1f，停止继续二轮处理",
                        self.tag, stage, len(scored), stop_when_valid, best_score,
                    )
                    return

        _evaluate_focus_list(focus_candidates, "首轮")

        # 若首轮没有强候选或整体信号明显不足，才重新搜索一轮。
        if self._should_trigger_second_search(scored):
            logger.info(
                "%s   首轮候选信号不足 valid=%d best=%.1f，触发二次候选搜索",
                self.tag, len(scored), max((c.score for c in scored), default=0.0),
            )
            rescue_queries = [
                q for q in self._gen_queries_once(task, existing=queries)
                if q and q not in queries
            ][:MIN_QUERIES]
            if rescue_queries:
                queries.extend(rescue_queries)
                rescue_hits = self._search_candidates(task, rescue_queries, queries_used)
                rescue_decisions = self._filter_candidates(task, rescue_hits)
                rescue_focus = (rescue_decisions.get("candidates") or [])[:SECOND_FOCUS_POOL_LIMIT]
                discarded.extend(
                    DiscardedCandidate(**d)
                    for d in rescue_decisions.get("discarded_candidates", [])
                )
                logger.info("%s   二次搜索保留重点候选 %d", self.tag, len(rescue_focus))
                _evaluate_focus_list(
                    rescue_focus,
                    "二轮",
                    stop_when_valid=SECOND_SEARCH_MIN_VALID,
                )
        else:
            logger.info(
                "%s   首轮已有足够强候选 valid=%d best=%.1f，跳过二次候选搜索",
                self.tag, len(scored), max((c.score for c in scored), default=0.0),
            )

        # ---------- S9-S10: 排序 + Top5 ----------
        scored.sort(key=lambda c: (c.score, *scoring.tiebreak_key(c)), reverse=True)
        top5: list[Candidate] = []
        for i, c in enumerate(scored[:TOP_K], start=1):
            c.rank = i
            top5.append(c)

        elapsed = round(time.monotonic() - t0, 2)
        logger.info(
            "%s DONE elapsed=%.1fs queries=%d top5=%d discarded=%d",
            self.tag, elapsed, len(queries_used), len(top5), len(discarded),
        )

        return AgentOutput(
            agent_name=self.persp.display_name,
            search_perspective=self.persp.perspective_label,
            patent_publication_no=task.patent.publication_no,
            queries_used=queries_used,
            top5_candidates=top5,
            discarded_candidates=discarded,
            elapsed_seconds=elapsed,
            llm_model=self.persp.llm_endpoint.model,
        )

    # ----------- S1 ------------
    def _gen_queries(self, task: TaskPackage) -> list[str]:
        queries = self._gen_queries_once(task)
        if len(queries) < MIN_QUERIES:
            logger.info(
                "%s   query 数 %d < %d，补调一次让 LLM 补全",
                self.tag, len(queries), MIN_QUERIES,
            )
            extra = self._gen_queries_once(task, existing=queries)
            seen = set()
            merged: list[str] = []
            for q in queries + extra:
                if q not in seen:
                    seen.add(q)
                    merged.append(q)
            queries = merged
        return queries[:MAX_QUERIES]

    def _gen_queries_once(self, task: TaskPackage, *, existing: list[str] | None = None) -> list[str]:
        system = prompts.load(self.persp.query_gen_prompt)
        user = prompts.render(
            "agent_query_gen_user",
            pub_no=task.patent.publication_no,
            title=task.patent.title or "(未知)",
            assignees=", ".join(task.patent.assignees) or "(未知)",
            industry_tag=task.industry_tag or "(未识别)",
            claim_1_text=task.claim_1_text,
            features_block=_format_features(task),
        )
        if existing:
            user += (
                "\n\n【已经生成过的 query（不要重复）】\n"
                + "\n".join(f"- {q}" for q in existing)
                + f"\n\n请再生成至少 {MIN_QUERIES} 条**与上面不同视角**的 query，"
                + "重点尝试加入行业知名厂商名（中文+英文）作为搜索锚点。"
            )
        logger.info(
            "%s   query generation LLM START mode=%s",
            self.tag, "supplement" if existing else "initial",
        )
        t0 = time.monotonic()
        data = chat_json(
            self.persp.llm_endpoint,
            system=system,
            user=user,
            temperature=0.3 if existing else 0.2,
            timeout=AGENT_LLM_TIMEOUT,
        )
        if isinstance(data, list):
            raw_queries = data
        elif isinstance(data, dict):
            raw_queries = data.get("queries", [])
        else:
            raw_queries = []
        queries = [str(q).strip() for q in raw_queries if str(q).strip()]
        logger.info(
            "%s   query generation LLM DONE count=%d elapsed=%.2fs",
            self.tag, len(queries), time.monotonic() - t0,
        )
        return queries

    # ----------- S2-S3 ------------
    def _search_candidates(
        self,
        task: TaskPackage,
        queries: list[str],
        queries_used: list[QueryRecord],
    ) -> list[SearchHit]:
        all_hits: dict[str, SearchHit] = {}
        for q in queries:
            try:
                hits = self.search_session.search(
                    q,
                    engines=self.persp.primary_engines,
                    num_per_engine=MAX_HITS_PER_ENGINE,
                    log_context=self.tag,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s   search %r 失败: %s", self.tag, q, exc)
                hits = []
            new_count = 0
            for h in hits:
                if h.url and h.url not in all_hits:
                    all_hits[h.url] = h
                    new_count += 1
            logger.info(
                "%s   query: %s → %d hits (%d 新)",
                self.tag, q[:60], len(hits), new_count,
            )
            queries_used.append(QueryRecord(
                query=q,
                search_engine="+".join(self.persp.primary_engines),
                purpose="候选竞品发现",
                n_results=len(hits),
            ))
            if len(all_hits) >= COARSE_POOL_LIMIT:
                break

        # 中国行业站点定向召回（仅在视角开启 cn_industry_routing 时）
        if (
            self.persp.cn_industry_routing
            and queries
            and len(all_hits) < COARSE_POOL_LIMIT
        ):
            self._search_cn_industry_sites(task, queries, queries_used, all_hits)

        return list(all_hits.values())[:COARSE_POOL_LIMIT]

    def _search_cn_industry_sites(
        self,
        task: TaskPackage,
        queries: list[str],
        queries_used: list[QueryRecord],
        all_hits: dict[str, SearchHit],
    ) -> None:
        """按 ``task.industry_tag`` 把已有 query 包装成 ``site:`` 限定，使用 Bocha 召回。

        每个 industry_tag 派生最多 ``CN_INDUSTRY_DERIVED_QUERIES`` 条 query
        （媒体组 + 厂商组），关键词复用 LLM 已生成的最聚焦的前 N 条。
        """
        sites = cn_industry.load_sites(task.industry_tag)
        if not sites:
            logger.info("%s   cn_industry: 无可用白名单，跳过", self.tag)
            return
        media, vendor = cn_industry.split_sites_by_priority(sites)
        media_filter = cn_industry.build_site_filter(media)
        vendor_filter = cn_industry.build_site_filter(vendor)
        # 取前 1~2 条最短的 query 作为关键词锚点（短 query 在 site: 限定下召回更高）
        anchors = sorted(queries, key=len)[:CN_INDUSTRY_DERIVED_QUERIES]
        derived: list[tuple[str, str]] = []
        if media_filter and anchors:
            derived.append((f"{anchors[0]} {media_filter}", "媒体/协会组"))
        if vendor_filter and len(anchors) > 1:
            derived.append((f"{anchors[1]} {vendor_filter}", "厂商官网组"))
        elif vendor_filter and anchors:
            derived.append((f"{anchors[0]} {vendor_filter}", "厂商官网组"))

        logger.info(
            "%s   cn_industry: tag=%s → %d 站点，派生 %d 条定向 query",
            self.tag, task.industry_tag or "(未识别)", len(sites), len(derived),
        )
        for q, group_name in derived:
            try:
                hits = self.search_session.search(
                    q,
                    engines=("bocha",),
                    num_per_engine=MAX_HITS_PER_ENGINE,
                    log_context=self.tag,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s   cn_industry %r 失败: %s", self.tag, group_name, exc)
                hits = []
            new_count = 0
            for h in hits:
                if h.url and h.url not in all_hits:
                    all_hits[h.url] = h
                    new_count += 1
            logger.info(
                "%s   cn_industry [%s]: %d hits (%d 新)",
                self.tag, group_name, len(hits), new_count,
            )
            queries_used.append(QueryRecord(
                query=q,
                search_engine="bocha (cn_industry)",
                purpose="候选竞品发现",
                n_results=len(hits),
            ))
            if len(all_hits) >= COARSE_POOL_LIMIT:
                return

    def _candidate_admission_failure(self, cand: dict[str, Any], task: TaskPackage) -> str | None:
        company = str(cand.get("company") or "").strip()
        product = str(cand.get("product") or "").strip()
        aliases = [str(a) for a in (cand.get("aliases") or [])]
        if not _is_clear_label(company):
            return "缺少明确竞品公司"
        if not _is_clear_label(product):
            return "缺少明确竞品产品/型号"
        if evidence_strategy.product_specificity_score(
            product,
            aliases,
            industry_tag=task.industry_tag,
        ) < 1:
            return "产品名称过泛，缺少可定位的型号、系列名或专有商品名"
        product_launch_date = normalize_date_string(cand.get("product_launch_date"))
        if is_after_application(product_launch_date, task.patent.application_date) is False:
            return (
                "竞品上市/发布/量产日期不晚于专利申请日"
                f"（竞品: {product_launch_date or '未知'}；申请日: "
                f"{task.patent.application_date or '未知'}）"
            )
        return None

    @staticmethod
    def _should_trigger_second_search(scored: list[Candidate]) -> bool:
        if not scored:
            return True
        best = max(c.score for c in scored)
        if best >= SECOND_SEARCH_STOP_SCORE:
            return False
        if len(scored) < SECOND_SEARCH_MIN_VALID and best < SECOND_SEARCH_TRIGGER_SCORE:
            return True
        return all(c.score < 70.0 for c in scored)

    def _search_industry_evidence_sites(
        self,
        *,
        task: TaskPackage,
        company: str,
        product: str,
        aliases: list[str],
        queries_used: list[QueryRecord],
        seen_queries: set[str],
        ev_urls: list[str],
        ev_titles: dict[str, str],
        ev_summaries: dict[str, str],
        ev_feature_hints: dict[str, set[str]],
    ) -> None:
        sites = cn_industry.load_sites(task.industry_tag)
        evidence_sites = [
            s for s in sites
            if "论坛" not in s.type
            if any(
                token in s.type
                for token in ("厂商官网", "规格", "资料", "经销", "代理", "供应", "手册", "PDF")
            )
        ]
        evidence_sites.sort(key=self._evidence_site_priority)
        site_filter = cn_industry.build_site_filter(evidence_sites, max_sites=8)
        if not site_filter:
            return
        feature_ids = tuple(f.feature_id for f in task.claim_features if f.feature_id)
        base = f"{company} {product}".strip()
        queries = [
            f"{base} datasheet specification 规格书 参数 产品手册 {site_filter}",
            f"{base} 经销商 供应商 代理商 PDF 规格 资料 {site_filter}",
        ]
        logger.info(
            "%s     evidence site seeds tag=%s sites=%d",
            self.tag,
            task.industry_tag or "(未识别)",
            len(evidence_sites),
        )
        for query in queries[:INDUSTRY_SITE_EVIDENCE_QUERY_LIMIT]:
            self._search_evidence_query(
                query=query,
                feature_ids=feature_ids,
                purpose="证据检索",
                queries_used=queries_used,
                seen_queries=seen_queries,
                ev_urls=ev_urls,
                ev_titles=ev_titles,
                ev_summaries=ev_summaries,
                ev_feature_hints=ev_feature_hints,
                company=company,
                product=product,
                aliases=aliases,
                industry_tag=task.industry_tag,
                engines=("tavily", "brave", "bocha"),
                url_pool_limit=EVIDENCE_URL_POOL_LIMIT,
            )

    @staticmethod
    def _evidence_site_priority(site) -> tuple[int, str]:
        if any(token in site.type for token in ("规格", "资料", "经销", "代理", "供应", "PDF")):
            return (0, site.domain)
        if "厂商官网" in site.type:
            return (1, site.domain)
        return (2, site.domain)

    # ----------- S4-S5 ------------
    def _filter_candidates(
        self,
        task: TaskPackage,
        hits: list[SearchHit],
    ) -> dict[str, Any]:
        if not hits:
            return {"candidates": [], "discarded_candidates": []}
        system = prompts.load("agent_candidate_filter")
        hits_block_lines: list[str] = []
        for i, h in enumerate(hits, start=1):
            hits_block_lines.append(
                f"[{i}] (源={h.source}) {h.title}\n"
                f"    URL: {h.url}\n"
                f"    发布时间: {h.published_date or '(未知)'}\n"
                f"    摘要: {h.snippet[:240]}"
            )
        user = prompts.render(
            "agent_candidate_filter_user",
            pub_no=task.patent.publication_no,
            title=task.patent.title or "(未知)",
            assignees=", ".join(task.patent.assignees) or "(未知)",
            application_date=task.patent.application_date or "(未知)",
            claim_1_text=task.claim_1_text,
            features_block=_format_features(task),
            n_hits=len(hits),
            hits_block="\n".join(hits_block_lines),
        )
        logger.info("%s   candidate_filter LLM START hits=%d", self.tag, len(hits))
        t0 = time.monotonic()
        data = chat_json(
            self.persp.llm_endpoint,
            system=system,
            user=user,
            temperature=0.1,
            timeout=AGENT_LLM_TIMEOUT,
        )
        if isinstance(data, list):
            data = {"candidates": [d for d in data if isinstance(d, dict)], "discarded_candidates": []}
        elif not isinstance(data, dict):
            data = {"candidates": [], "discarded_candidates": []}
        logger.info(
            "%s   candidate_filter LLM DONE candidates=%d discarded=%d elapsed=%.2fs",
            self.tag,
            len(data.get("candidates") or []),
            len(data.get("discarded_candidates") or []),
            time.monotonic() - t0,
        )
        return data

    # ----------- S6-S7 ------------
    def _evaluate_candidate(
        self,
        task: TaskPackage,
        cand: dict[str, Any],
        queries_used: list[QueryRecord],
    ) -> Candidate:
        company = (cand.get("company") or "").strip()
        product = (cand.get("product") or "").strip()
        aliases = [str(a) for a in (cand.get("aliases") or [])]
        product_launch_date = normalize_date_string(cand.get("product_launch_date"))
        product_launch_date_evidence_url = str(
            cand.get("product_launch_date_evidence_url") or ""
        ).strip() or None
        initial_ev = cand.get("initial_evidence") or []

        # S6 证据补充检索按“证据目标”分组：一份规格书/产品页可同时支撑
        # 多个相关特征，因此先按目标生成中英 query，再把命中的 URL 标注到
        # 对应的一组 Fi 上。
        ev_urls: list[str] = []
        ev_titles: dict[str, str] = {}
        ev_summaries: dict[str, str] = {}
        for e in initial_ev:
            if not isinstance(e, dict) or not e.get("url"):
                continue
            url = evidence_strategy.canonicalize_url(str(e.get("url", "")))
            title = str(e.get("title", "") or "")
            snippet = str(e.get("snippet", "") or "")
            if not evidence_strategy.is_relevant_hit(
                url,
                title,
                snippet,
                company,
                product,
                aliases,
                industry_tag=task.industry_tag,
            ):
                logger.info("%s     initial evidence SKIP low_relevance url=%s", self.tag, url)
                continue
            if url not in ev_urls:
                ev_urls.append(url)
                ev_titles[url] = title
                ev_summaries[url] = snippet
        ev_feature_hints: dict[str, set[str]] = {}
        seen_evidence_queries: set[str] = set()
        evidence_targets = evidence_strategy.build_evidence_targets(
            company,
            product,
            task.claim_features,
            industry_tag=task.industry_tag,
        )
        logger.info(
            "%s     evidence targets START count=%d",
            self.tag,
            len(evidence_targets),
        )
        for target in evidence_targets[:EVIDENCE_TARGET_LIMIT]:
            if target.target_id == "market_date":
                continue
            logger.info(
                "%s     evidence target=%s features=%s queries=%d",
                self.tag,
                target.label,
                ",".join(target.feature_ids) or "(候选事实)",
                min(len(target.queries), EVIDENCE_QUERIES_PER_TARGET),
            )
            for query in target.queries[:EVIDENCE_QUERIES_PER_TARGET]:
                self._search_evidence_query(
                    query=query,
                    feature_ids=target.feature_ids,
                    purpose="证据检索",
                    queries_used=queries_used,
                    seen_queries=seen_evidence_queries,
                    ev_urls=ev_urls,
                    ev_titles=ev_titles,
                    ev_summaries=ev_summaries,
                    ev_feature_hints=ev_feature_hints,
                    company=company,
                    product=product,
                    aliases=aliases,
                    industry_tag=task.industry_tag,
                    engines=self._engines_for_evidence_target(target, phase="initial"),
                    url_pool_limit=EVIDENCE_URL_POOL_LIMIT,
                )
        if not (product_launch_date and product_launch_date_evidence_url):
            market_date_target = next(
                (target for target in evidence_targets if target.target_id == "market_date"),
                None,
            )
            if market_date_target:
                logger.info(
                    "%s     market date evidence target=%s queries=%d",
                    self.tag,
                    market_date_target.label,
                    min(len(market_date_target.queries), MARKET_DATE_QUERIES_PER_CANDIDATE),
                )
                for query in market_date_target.queries[:MARKET_DATE_QUERIES_PER_CANDIDATE]:
                    self._search_evidence_query(
                        query=query,
                        feature_ids=(),
                        purpose="证据检索",
                        queries_used=queries_used,
                        seen_queries=seen_evidence_queries,
                        ev_urls=ev_urls,
                        ev_titles=ev_titles,
                        ev_summaries=ev_summaries,
                        ev_feature_hints=ev_feature_hints,
                        company=company,
                        product=product,
                        aliases=aliases,
                        industry_tag=task.industry_tag,
                        engines=self._engines_for_evidence_target(
                            market_date_target,
                            phase="initial",
                        ),
                        url_pool_limit=EVIDENCE_URL_POOL_LIMIT,
                    )
        self._search_industry_evidence_sites(
            task=task,
            company=company,
            product=product,
            aliases=aliases,
            queries_used=queries_used,
            seen_queries=seen_evidence_queries,
            ev_urls=ev_urls,
            ev_titles=ev_titles,
            ev_summaries=ev_summaries,
            ev_feature_hints=ev_feature_hints,
        )

        # 中国上市公司：用巨潮资讯查公告 / 年报全文（仅 deepseek 视角触发）
        if self.persp.cn_industry_routing and company:
            cninfo_query = f"{company} {product}".strip() or company
            try:
                logger.info("%s     cninfo START query=%r", self.tag, cninfo_query)
                t0 = time.monotonic()
                cn_hits = cninfo.search(cninfo_query, num=CNINFO_HITS_PER_CANDIDATE)
                logger.info(
                    "%s     cninfo DONE hits=%d elapsed=%.2fs query=%r",
                    self.tag, len(cn_hits), time.monotonic() - t0, cninfo_query,
                )
            except SearchError as exc:
                logger.info("%s     cninfo 查询失败: %s", self.tag, exc)
                cn_hits = []
            if cn_hits:
                queries_used.append(QueryRecord(
                    query=cninfo_query,
                    search_engine="cninfo",
                    purpose="证据检索",
                    n_results=len(cn_hits),
                ))
                added = 0
                for h in cn_hits:
                    url = evidence_strategy.canonicalize_url(h.url)
                    if url and url not in ev_urls:
                        ev_urls.append(url)
                        ev_titles[url] = h.title
                        ev_summaries[url] = h.snippet
                        added += 1
                        logger.info("%s     cninfo HIT title=%r url=%s", self.tag, h.title[:160], url)
                logger.info(
                    "%s     cninfo 公告补搜 %r → %d 条 (%d 新)",
                    self.tag, cninfo_query, len(cn_hits), added,
                )

        ev_urls = self._sort_and_log_evidence_urls(
            ev_urls,
            ev_titles,
            phase="initial",
            industry_tag=task.industry_tag,
        )
        budget = self._evidence_budget(cand, phase="initial", industry_tag=task.industry_tag)
        pages_by_url: dict[str, ExtractedPage] = {}
        crawled_targets: set[str] = set()
        pages = self._read_candidate_pages(
            ev_urls=ev_urls,
            ev_titles=ev_titles,
            ev_summaries=ev_summaries,
            pages_by_url=pages_by_url,
            crawled_targets=crawled_targets,
            queries_used=queries_used,
            budget=budget,
            industry_tag=task.industry_tag,
        )
        match = self._run_feature_match(
            task=task,
            company=company,
            product=product,
            aliases=aliases,
            pages=pages,
            ev_titles=ev_titles,
            ev_feature_hints=ev_feature_hints,
            pass_label="initial",
            industry_tag=task.industry_tag,
        )

        gap_features = self._gap_features_for_supplement(
            task,
            match["feature_matches"],
            match["remaining_gaps"],
        )
        initial_score = scoring.candidate_total_score(
            match["feature_matches"],
            feature_ids=[f.feature_id for f in task.claim_features],
        )
        initial_positive = sum(
            1 for fm in match["feature_matches"]
            if fm.judgement in ("明确满足", "可能满足")
        )
        if (
            gap_features
            and (
                initial_score < MIN_INITIAL_SCORE_FOR_GAP
                or initial_positive < MIN_INITIAL_POSITIVE_FEATURES_FOR_GAP
            )
        ):
            logger.info(
                "%s     gap supplement SKIP reason=low_initial_signal score=%.1f positives=%d",
                self.tag, initial_score, initial_positive,
            )
            gap_features = []
        if gap_features:
            logger.info(
                "%s     gap supplement START features=%s",
                self.tag,
                ",".join(f.feature_id for f in gap_features),
            )
            before_urls = set(ev_urls)
            gap_targets = evidence_strategy.build_evidence_targets(
                company,
                product,
                gap_features,
                industry_tag=task.industry_tag,
                include_counter=True,
            )
            for target in gap_targets[:GAP_EVIDENCE_TARGET_LIMIT]:
                if not target.feature_ids:
                    continue
                if target.target_id == "market_date":
                    continue
                logger.info(
                    "%s     gap target=%s features=%s queries=%d",
                    self.tag,
                    target.label,
                    ",".join(target.feature_ids) or "(候选事实)",
                    min(len(target.queries), GAP_EVIDENCE_QUERIES_PER_TARGET),
                )
                for query in target.queries[:GAP_EVIDENCE_QUERIES_PER_TARGET]:
                    self._search_evidence_query(
                        query=query,
                        feature_ids=target.feature_ids,
                        purpose="证据检索",
                        queries_used=queries_used,
                        seen_queries=seen_evidence_queries,
                        ev_urls=ev_urls,
                        ev_titles=ev_titles,
                        ev_summaries=ev_summaries,
                        ev_feature_hints=ev_feature_hints,
                        company=company,
                        product=product,
                        aliases=aliases,
                        industry_tag=task.industry_tag,
                        engines=self._engines_for_evidence_target(target, phase="gap"),
                        url_pool_limit=budget.url_pool_limit,
                    )
            for feature in gap_features:
                if any(feature.feature_id in target.feature_ids for target in gap_targets):
                    continue
                for query in evidence_strategy.build_feature_evidence_queries(
                    company,
                    product,
                    feature,
                    industry_tag=task.industry_tag,
                )[:GAP_EVIDENCE_QUERIES_PER_TARGET]:
                    self._search_evidence_query(
                        query=query,
                        feature_ids=(feature.feature_id,),
                        purpose="证据检索",
                        queries_used=queries_used,
                        seen_queries=seen_evidence_queries,
                        ev_urls=ev_urls,
                        ev_titles=ev_titles,
                        ev_summaries=ev_summaries,
                        ev_feature_hints=ev_feature_hints,
                        company=company,
                        product=product,
                        aliases=aliases,
                        industry_tag=task.industry_tag,
                        engines=pool.DEFAULT_SEARCH_ENGINES,
                        url_pool_limit=budget.url_pool_limit,
                    )
            ev_urls = self._sort_and_log_evidence_urls(
                ev_urls,
                ev_titles,
                phase="gap",
                industry_tag=task.industry_tag,
            )
            gap_budget = self._evidence_budget(
                cand,
                phase="gap",
                initial_score=initial_score,
                industry_tag=task.industry_tag,
            )
            pages = self._read_candidate_pages(
                ev_urls=ev_urls,
                ev_titles=ev_titles,
                ev_summaries=ev_summaries,
                pages_by_url=pages_by_url,
                crawled_targets=crawled_targets,
                queries_used=queries_used,
                budget=gap_budget,
                industry_tag=task.industry_tag,
            )
            logger.info(
                "%s     gap supplement DONE new_urls=%d pages=%d",
                self.tag,
                len(set(ev_urls) - before_urls),
                len(pages),
            )
            match = self._run_feature_match(
                task=task,
                company=company,
                product=product,
                aliases=aliases,
                pages=pages,
                ev_titles=ev_titles,
                ev_feature_hints=ev_feature_hints,
                pass_label="gap",
                industry_tag=task.industry_tag,
            )
        else:
            logger.info("%s     gap supplement SKIP reason=no_target_gap", self.tag)

        feature_matches = match["feature_matches"]
        page_url_set = match["packed_urls"]
        evidence_url_set = sorted({
            ev.url for fm in feature_matches for ev in fm.evidence if ev.url
        } | set(ev_urls[:EVIDENCE_READ_URL_LIMIT]) | page_url_set)
        hard = scoring.evaluate_hard_rules(
            company=company,
            product=product,
            assignees=task.patent.assignees,
            evidence_urls=evidence_url_set,
            feature_matches=feature_matches,
            patent_application_date=task.patent.application_date,
            product_launch_date=product_launch_date,
        )
        total = scoring.candidate_total_score(
            feature_matches,
            feature_ids=[f.feature_id for f in task.claim_features],
        )
        return Candidate(
            rank=0,
            company=company,
            product=product,
            aliases=aliases,
            product_launch_date=product_launch_date,
            product_launch_date_evidence_url=product_launch_date_evidence_url,
            score=total,
            hard_rule_check=hard,
            feature_match_table=feature_matches,
            main_evidence_urls=evidence_url_set,
            remaining_gaps=match["remaining_gaps"],
            reason_for_top5=match["reason_for_top5"],
        )

    def _engines_for_evidence_target(
        self,
        target: evidence_strategy.EvidenceTarget,
        *,
        phase: str,
    ) -> tuple[str, ...]:
        if phase == "gap" and target.target_id in {"counter", "feature"}:
            return pool.DEFAULT_SEARCH_ENGINES
        if target.target_id == "market_date":
            return ("bocha", "tavily", "brave_news")
        if target.target_id == "spec":
            return ("tavily", "brave", "exa")
        if target.target_id in {"structure", "algorithm", "product_docs"}:
            return ("tavily", "exa", "brave")
        if target.target_id == "counter":
            return pool.DEFAULT_SEARCH_ENGINES
        return ("tavily", "exa", "brave")

    def _evidence_budget(
        self,
        cand: dict[str, Any],
        *,
        phase: str,
        initial_score: float | None = None,
        industry_tag: str | None = None,
    ) -> EvidenceBudget:
        product = str(cand.get("product") or "")
        aliases = [str(a) for a in (cand.get("aliases") or [])]
        specificity = evidence_strategy.product_specificity_score(
            product,
            aliases,
            industry_tag=industry_tag,
        )
        if phase == "gap" and (initial_score or 0.0) >= 75.0:
            return EvidenceBudget(read_url_limit=8, page_limit=12, url_pool_limit=30)
        if specificity >= 3:
            return EvidenceBudget(read_url_limit=6, page_limit=10, url_pool_limit=28)
        return EvidenceBudget()

    def _search_evidence_query(
        self,
        *,
        query: str,
        feature_ids: list[str] | tuple[str, ...] | None,
        purpose: str,
        queries_used: list[QueryRecord],
        seen_queries: set[str],
        ev_urls: list[str],
        ev_titles: dict[str, str],
        ev_summaries: dict[str, str],
        ev_feature_hints: dict[str, set[str]],
        company: str,
        product: str,
        aliases: list[str],
        industry_tag: str | None = None,
        engines: list[str] | tuple[str, ...] | None = None,
        url_pool_limit: int = EVIDENCE_URL_POOL_LIMIT,
    ) -> None:
        if not query:
            return
        feature_ids = tuple(fid for fid in (feature_ids or ()) if fid)
        qkey = evidence_strategy.normalize_query(query)
        if qkey in seen_queries:
            logger.info("%s     evidence query SKIP duplicate query=%r", self.tag, query)
            return
        seen_queries.add(qkey)
        evidence_engines = tuple(engines or pool.DEFAULT_SEARCH_ENGINES)
        try:
            extra = self.search_session.search(
                query,
                engines=evidence_engines,
                num_per_engine=EVIDENCE_HITS_PER_QUERY,
                log_context=self.tag,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s     evidence search %r 失败: %s", self.tag, query, exc)
            extra = []
        queries_used.append(QueryRecord(
            query=query,
            search_engine="+".join(evidence_engines),
            purpose=purpose,
            n_results=len(extra),
        ))
        logger.info(
            "%s     证据补搜 [%s]%s → %d 条 query=%r",
            self.tag,
            "+".join(evidence_engines),
            f" {','.join(feature_ids)}" if feature_ids else "",
            len(extra),
            query,
        )
        for h in extra:
            if not h.url:
                continue
            url = evidence_strategy.canonicalize_url(h.url)
            if not evidence_strategy.is_relevant_hit(
                url,
                h.title,
                h.snippet,
                company,
                product,
                aliases,
                industry_tag=industry_tag,
            ):
                logger.info(
                    "%s     evidence HIT SKIP low_relevance source=%s title=%r url=%s",
                    self.tag, h.source, (h.title or "")[:120], url,
                )
                continue
            for feature_id in feature_ids:
                ev_feature_hints.setdefault(url, set()).add(feature_id)
            if url not in ev_urls and len(ev_urls) < url_pool_limit:
                ev_urls.append(url)
                ev_titles[url] = h.title
                ev_summaries[url] = h.snippet

    def _sort_and_log_evidence_urls(
        self,
        ev_urls: list[str],
        ev_titles: dict[str, str],
        *,
        phase: str,
        industry_tag: str | None = None,
    ) -> list[str]:
        sorted_urls = evidence_strategy.sort_urls_by_value(
            ev_urls,
            ev_titles,
            industry_tag=industry_tag,
        )
        logger.info(
            "%s     evidence URL pool sorted phase=%s total=%d",
            self.tag, phase, len(sorted_urls),
        )
        for i, url in enumerate(sorted_urls, start=1):
            logger.info(
                "%s     evidence URL[%d] tier=%s title=%r url=%s",
                self.tag,
                i,
                evidence_strategy.tier_label(
                    url,
                    ev_titles.get(url, ""),
                    industry_tag=industry_tag,
                ),
                (ev_titles.get(url, "") or "")[:160],
                url,
            )
        return sorted_urls

    def _read_candidate_pages(
        self,
        *,
        ev_urls: list[str],
        ev_titles: dict[str, str],
        ev_summaries: dict[str, str],
        pages_by_url: dict[str, ExtractedPage],
        crawled_targets: set[str],
        queries_used: list[QueryRecord],
        budget: EvidenceBudget,
        industry_tag: str | None = None,
    ) -> list[ExtractedPage]:
        # 抽取正文（优先官方 / 产品手册 / PDF / 文档中心等高价值来源）
        read_candidates = [
            url for url in ev_urls
            if evidence_strategy.should_read_url(
                url,
                ev_titles.get(url, ""),
                industry_tag=industry_tag,
            )
        ]
        skipped_read = [url for url in ev_urls if url not in read_candidates]
        for url in skipped_read[:10]:
            logger.info(
                "%s     read SKIP reason=unreadable_or_patent tier=%s url=%s",
                self.tag,
                evidence_strategy.tier_label(
                    url,
                    ev_titles.get(url, ""),
                    industry_tag=industry_tag,
                ),
                url,
            )
        for url in read_candidates[:budget.read_url_limit]:
            if url in pages_by_url:
                continue
            try:
                p = self.search_session.read_url(url, log_context=self.tag)
                pages_by_url[url] = p
                logger.info(
                    "%s     read %s → %s, %d chars",
                    self.tag, url[:60], p.source, len(p.text),
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("%s     read %s 失败 (用 snippet 兜底): %s", self.tag, url[:60], exc)
                pages_by_url[url] = ExtractedPage(
                    url=url,
                    title=ev_titles.get(url, ""),
                    text=ev_summaries.get(url, ""),
                    source="snippet_fallback",
                )

        # Tavily Crawl 只深挖官网 / 产品页 / 文档中心，避免把新闻站或论坛页当成站点入口。
        crawl_targets = [
            url for url in ev_urls
            if evidence_strategy.is_crawl_worthy(
                url,
                ev_titles.get(url, ""),
                industry_tag=industry_tag,
            )
        ][:budget.crawl_targets]
        skipped_crawl = [url for url in ev_urls if url not in crawl_targets]
        for url in skipped_crawl[:10]:
            logger.info(
                "%s     crawl SKIP reason=not_crawl_worthy tier=%s url=%s",
                self.tag,
                evidence_strategy.tier_label(
                    url,
                    ev_titles.get(url, ""),
                    industry_tag=industry_tag,
                ),
                url,
            )
        for crawl_url in crawl_targets:
            if len(pages_by_url) >= budget.page_limit or crawl_url in crawled_targets:
                continue
            crawled_targets.add(crawl_url)
            try:
                crawled = self.search_session.crawl_url(
                    crawl_url,
                    max_depth=1,
                    limit=budget.crawl_pages,
                    log_context=self.tag,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("%s     crawl FAIL url=%s error=%s", self.tag, crawl_url[:60], exc)
                crawled = []
            for p in crawled:
                if p.url and p.url not in pages_by_url:
                    pages_by_url[p.url] = p
                if len(pages_by_url) >= budget.page_limit:
                    break
            if crawled:
                queries_used.append(QueryRecord(
                    query=crawl_url,
                    search_engine="tavily_crawl",
                    purpose="证据检索",
                    n_results=len(crawled),
                ))

        ordered: list[ExtractedPage] = []
        seen: set[str] = set()
        for url in read_candidates[:budget.read_url_limit]:
            page = pages_by_url.get(url)
            if page and page.url not in seen:
                ordered.append(page)
                seen.add(page.url)
        for page in pages_by_url.values():
            if len(ordered) >= budget.page_limit:
                break
            if page.url and page.url not in seen:
                ordered.append(page)
                seen.add(page.url)
        return ordered[:budget.page_limit]

    def _run_feature_match(
        self,
        *,
        task: TaskPackage,
        company: str,
        product: str,
        aliases: list[str],
        pages: list[ExtractedPage],
        ev_titles: dict[str, str],
        ev_feature_hints: dict[str, set[str]],
        pass_label: str,
        industry_tag: str | None = None,
    ) -> dict[str, Any]:
        # ↓↓↓ 上下文动态压缩
        feat_block = _format_features(task)
        fixed_overhead_chars = (
            len(prompts.load("agent_feature_match"))
            + len(task.claim_1_text)
            + len(feat_block)
            + len(company) + len(product) + 2000  # 留余量给模板和 reasoning
        )
        ctx_window = self.persp.llm_endpoint.context_window or 128_000
        summary_context = (
            f"专利权要 1：{task.claim_1_text[:300]}…\n"
            f"目标候选：{company} / {product}\n"
            f"技术特征要点：{feat_block[:600]}"
        )
        packed_pages, pack_info = compactor.pack_evidence(
            pages,
            ctx_window=ctx_window,
            fixed_overhead_chars=fixed_overhead_chars,
            summary_context=summary_context,
        )
        if (
            pack_info.excerpted_count
            or pack_info.summarized_count
            or pack_info.truncated_count
            or pack_info.dropped_count
        ):
            logger.info(
                "%s     compactor: 总 %d/%d tokens · 摘录 %d · 摘要 %d · 截断 %d · 丢弃 %d",
                self.tag, pack_info.total_tokens, pack_info.budget_tokens,
                pack_info.excerpted_count, pack_info.summarized_count,
                pack_info.truncated_count, pack_info.dropped_count,
            )

        # S7 LLM 特征匹配
        evidence_block_lines: list[str] = []
        for j, p in enumerate(packed_pages, start=1):
            hints = sorted(ev_feature_hints.get(p.url, set()))
            hint_text = f"\n     线索特征: {', '.join(hints)}" if hints else ""
            source_label = evidence_strategy.tier_label(
                p.url,
                p.title or ev_titles.get(p.url, ""),
                industry_tag=industry_tag,
            )
            evidence_block_lines.append(
                f"[E{j}] {p.title or ev_titles.get(p.url, '')}\n"
                f"     URL: {p.url}\n"
                f"     来源层级: {source_label}{hint_text}\n"
                f"     正文片段: {p.text}"
            )

        logger.info(
            "%s     feature_match LLM START pass=%s candidate=%s/%s evidence_pages=%d",
            self.tag, pass_label, company, product, len(evidence_block_lines),
        )
        system = prompts.load("agent_feature_match")
        user = prompts.render(
            "agent_feature_match_user",
            pub_no=task.patent.publication_no,
            title=task.patent.title or "(未知)",
            assignees=", ".join(task.patent.assignees) or "(未知)",
            claim_1_text=task.claim_1_text,
            features_block=_format_features(task),
            company=company,
            product=product,
            aliases=", ".join(aliases) or "(无)",
            n_evidence=len(evidence_block_lines),
            evidence_block="\n\n".join(evidence_block_lines) or "(无证据)",
        )
        t0 = time.monotonic()
        data = chat_json(
            self.persp.llm_endpoint,
            system=system,
            user=user,
            temperature=0.1,
            timeout=AGENT_LLM_TIMEOUT,
        )
        logger.info(
            "%s     feature_match LLM DONE pass=%s candidate=%s/%s elapsed=%.2fs",
            self.tag, pass_label, company, product, time.monotonic() - t0,
        )

        if isinstance(data, list):
            data = {"feature_match_table": [d for d in data if isinstance(d, dict)]}
        elif not isinstance(data, dict):
            data = {"feature_match_table": []}

        feature_matches: list[FeatureMatch] = []
        feature_text_by_id = {f.feature_id: f.feature_text for f in task.claim_features}
        allowed_evidence_urls = {p.url for p in packed_pages if p.url}
        for raw in data.get("feature_match_table", []) or []:
            if not isinstance(raw, dict):
                continue
            fid = str(raw.get("feature_id", "")).strip()
            judg = str(raw.get("judgement", "证据不足")).strip()
            if judg not in scoring.JUDGEMENT_SCORE:
                judg = "证据不足"
            score = scoring.JUDGEMENT_SCORE[judg]
            ev_list = []
            for re_ev in raw.get("evidence", []) or []:
                if not isinstance(re_ev, dict):
                    continue
                ev_url = str(re_ev.get("url", "")).strip()
                if ev_url and ev_url not in allowed_evidence_urls:
                    logger.info("%s     丢弃未输入模型的证据 URL: %s", self.tag, ev_url[:80])
                    continue
                ev_list.append(Evidence(
                    url=ev_url,
                    title=str(re_ev.get("title", "")).strip(),
                    source_type=_normalize_source_type(re_ev.get("source_type")),
                    source_reliability=_normalize_reliability(re_ev.get("source_reliability")),
                    summary=str(re_ev.get("summary", "")).strip(),
                    supported_features=[str(s) for s in (re_ev.get("supported_features") or [fid])],
                ))
            feature_matches.append(FeatureMatch(
                feature_id=fid,
                claim_feature=feature_text_by_id.get(fid, ""),
                judgement=judg,  # type: ignore[arg-type]
                score=score,
                reasoning=str(raw.get("reasoning", "")).strip(),
                evidence=ev_list,
            ))
        feature_matches = scoring.normalize_feature_matches(feature_matches, task.claim_features)
        # 紧凑日志：每个特征一行 judgement
        judg_summary = ", ".join(f"{m.feature_id}={m.judgement}" for m in feature_matches)
        logger.info("%s     特征判断 pass=%s: %s", self.tag, pass_label, judg_summary)
        return {
            "feature_matches": feature_matches,
            "remaining_gaps": data.get("remaining_gaps", []) or [],
            "reason_for_top5": str(data.get("reason_for_top5", "")).strip(),
            "packed_urls": {p.url for p in packed_pages if p.url},
        }

    def _gap_features_for_supplement(
        self,
        task: TaskPackage,
        feature_matches: list[FeatureMatch],
        remaining_gaps: list[Any],
    ):
        gap_ids: set[str] = set()
        for item in remaining_gaps:
            if isinstance(item, dict):
                fid = str(item.get("feature_id", "")).strip()
            else:
                fid = str(item).strip()
            if fid:
                gap_ids.add(fid)

        match_by_id = {fm.feature_id: fm for fm in feature_matches}
        targets = []
        for feature in task.claim_features:
            fm = match_by_id.get(feature.feature_id)
            if fm is None or fm.judgement == "明确不满足":
                continue
            has_url = any(ev.url for ev in fm.evidence)
            if fm.judgement == "证据不足" or feature.feature_id in gap_ids or not has_url:
                targets.append(feature)
        targets.sort(key=lambda f: not f.is_essential)
        return targets[:GAP_FEATURE_SUPPLEMENT_LIMIT]


def _format_features(task: TaskPackage) -> str:
    lines = []
    for f in task.claim_features:
        terms = "、".join(f.engineering_terms) if f.engineering_terms else "(无)"
        mkts = "、".join(f.marketing_terms) if f.marketing_terms else "(无)"
        lines.append(
            f"- {f.feature_id}: {f.feature_text}\n"
            f"      工程术语: {terms}\n"
            f"      行业宣传语: {mkts}"
        )
    return "\n".join(lines)


def _is_clear_label(value: str) -> bool:
    raw = (value or "").strip()
    if len(raw) < 2:
        return False
    low = raw.lower()
    vague = {
        "unknown",
        "n/a",
        "na",
        "none",
        "未知",
        "不详",
        "未明确",
        "未识别",
        "竞品",
        "产品",
        "电池",
        "电芯",
        "动力电池",
        "方形电池",
    }
    return low not in vague and raw not in vague
