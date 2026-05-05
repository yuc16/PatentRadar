"""SearchAgent 工作流（PRD §8.1 S0~S10）。"""

from __future__ import annotations

import logging
import time
from typing import Any

from .. import compactor, prompts, scoring
from ..config import AGENT_LLM_TIMEOUT
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
from .perspectives import AgentPerspective

logger = logging.getLogger("patentradar.agent")


# 每阶段的可调参数（PRD §8.2 / §17.4 成本控制）
MIN_QUERIES = 5                  # 候选发现 query 数下界（不足会触发二次补全）
MAX_QUERIES = 10                 # 候选发现 query 数上界
MAX_HITS_PER_ENGINE = 8          # 每引擎单次返回 hits 数
COARSE_POOL_LIMIT = 40           # 粗候选池上限（黑名单过滤后实际有效 < 此数）
FOCUS_POOL_LIMIT = 12            # 重点候选数（PRD §8.2: 8~12）
EVIDENCE_PER_CANDIDATE = 5       # 每个候选最多读取的正文数
TOP_K = 5

# 中国行业路由：每条原 query 衍生出 site: 限定 query 的最大数（媒体组 + 厂商组）
CN_INDUSTRY_DERIVED_QUERIES = 2
# 巨潮资讯证据补搜上限（每个候选最多取 N 篇公告）
CNINFO_HITS_PER_CANDIDATE = 3

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
    def __init__(self, perspective: AgentPerspective):
        self.persp = perspective
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
        focus_candidates = candidate_decisions["candidates"][:FOCUS_POOL_LIMIT]
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
        for idx, c in enumerate(focus_candidates, start=1):
            label = f"{c.get('company')}/{c.get('product')}"
            logger.info(
                "%s S6-S7 [%d/%d] 处理候选 %s",
                self.tag, idx, len(focus_candidates), label,
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

        # ---------- S9-S10: 排序 + Top5 ----------
        scored.sort(key=lambda c: (-c.score, scoring.tiebreak_key(c)))
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
        data = chat_json(
            self.persp.llm_endpoint,
            system=system,
            user=user,
            temperature=0.3 if existing else 0.2,
            timeout=AGENT_LLM_TIMEOUT,
        )
        return [str(q).strip() for q in data.get("queries", []) if str(q).strip()]

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
                hits = pool.search(
                    q,
                    engines=self.persp.primary_engines,
                    num_per_engine=MAX_HITS_PER_ENGINE,
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
                hits = pool.search(q, engines=("bocha",), num_per_engine=MAX_HITS_PER_ENGINE)
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
                f"[{i}] (源={h.source}) {h.title}\n    URL: {h.url}\n    摘要: {h.snippet[:240]}"
            )
        user = prompts.render(
            "agent_candidate_filter_user",
            pub_no=task.patent.publication_no,
            title=task.patent.title or "(未知)",
            assignees=", ".join(task.patent.assignees) or "(未知)",
            claim_1_text=task.claim_1_text,
            features_block=_format_features(task),
            n_hits=len(hits),
            hits_block="\n".join(hits_block_lines),
        )
        return chat_json(
            self.persp.llm_endpoint,
            system=system,
            user=user,
            temperature=0.1,
            timeout=AGENT_LLM_TIMEOUT,
        )

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
        initial_ev = cand.get("initial_evidence") or []

        # S6 证据补充检索（每个候选用"company + product"再做一次共享池搜索）
        ev_urls: list[str] = [e.get("url", "") for e in initial_ev if e.get("url")]
        ev_titles: dict[str, str] = {
            e.get("url", ""): e.get("title", "") for e in initial_ev
        }
        ev_summaries: dict[str, str] = {
            e.get("url", ""): e.get("snippet", "") for e in initial_ev
        }
        try:
            extra_engines = tuple(set(self.persp.primary_engines + ("tavily",)))
            extra = pool.search(
                f"{company} {product}",
                engines=extra_engines,
                num_per_engine=4,
            )
            queries_used.append(QueryRecord(
                query=f"{company} {product}",
                search_engine="+".join(extra_engines),
                purpose="证据检索",
                n_results=len(extra),
            ))
            logger.info(
                "%s     证据补搜 [%s] → %d 条新增",
                self.tag, "+".join(extra_engines), len(extra),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s     extra search 失败: %s", self.tag, exc)
            extra = []
        for h in extra:
            if h.url and h.url not in ev_urls:
                ev_urls.append(h.url)
                ev_titles[h.url] = h.title
                ev_summaries[h.url] = h.snippet
            if len(ev_urls) >= EVIDENCE_PER_CANDIDATE * 2:
                break

        # 中国上市公司：用巨潮资讯查公告 / 年报全文（仅 deepseek 视角触发）
        if self.persp.cn_industry_routing and company:
            cninfo_query = f"{company} {product}".strip() or company
            try:
                cn_hits = cninfo.search(cninfo_query, num=CNINFO_HITS_PER_CANDIDATE)
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
                    if h.url and h.url not in ev_urls:
                        ev_urls.append(h.url)
                        ev_titles[h.url] = h.title
                        ev_summaries[h.url] = h.snippet
                        added += 1
                logger.info(
                    "%s     cninfo 公告补搜 %r → %d 条 (%d 新)",
                    self.tag, cninfo_query, len(cn_hits), added,
                )

        # 抽取正文（最多 EVIDENCE_PER_CANDIDATE 条）
        pages: list[ExtractedPage] = []
        for url in ev_urls[:EVIDENCE_PER_CANDIDATE]:
            try:
                p = pool.read_url(url)
                pages.append(p)
                logger.info(
                    "%s     read %s → %s, %d chars",
                    self.tag, url[:60], p.source, len(p.text),
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("%s     read %s 失败 (用 snippet 兜底): %s", self.tag, url[:60], exc)
                pages.append(ExtractedPage(
                    url=url,
                    title=ev_titles.get(url, ""),
                    text=ev_summaries.get(url, ""),
                    source="snippet_fallback",
                ))

        # ↓↓↓ 上下文动态压缩（PRD §17.4）
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
        if pack_info.summarized_count or pack_info.truncated_count or pack_info.dropped_count:
            logger.info(
                "%s     compactor: 总 %d/%d tokens · 摘要 %d · 截断 %d · 丢弃 %d",
                self.tag, pack_info.total_tokens, pack_info.budget_tokens,
                pack_info.summarized_count, pack_info.truncated_count, pack_info.dropped_count,
            )

        # S7 LLM 特征匹配
        evidence_block_lines: list[str] = []
        for j, p in enumerate(packed_pages, start=1):
            evidence_block_lines.append(
                f"[E{j}] {p.title or ev_titles.get(p.url, '')}\n     URL: {p.url}\n     正文片段: {p.text}"
            )

        logger.info("%s     LLM 特征匹配中 …", self.tag)
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
        data = chat_json(
            self.persp.llm_endpoint,
            system=system,
            user=user,
            temperature=0.1,
            timeout=AGENT_LLM_TIMEOUT,
        )

        feature_matches: list[FeatureMatch] = []
        feature_text_by_id = {f.feature_id: f.feature_text for f in task.claim_features}
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
                ev_list.append(Evidence(
                    url=str(re_ev.get("url", "")).strip(),
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
        # 紧凑日志：每个特征一行 judgement
        judg_summary = ", ".join(f"{m.feature_id}={m.judgement}" for m in feature_matches)
        logger.info("%s     特征判断: %s", self.tag, judg_summary)

        evidence_url_set = sorted({
            ev.url for fm in feature_matches for ev in fm.evidence if ev.url
        } | set(ev_urls[:EVIDENCE_PER_CANDIDATE]))
        hard = scoring.evaluate_hard_rules(
            company=company,
            product=product,
            assignees=task.patent.assignees,
            evidence_urls=evidence_url_set,
            feature_matches=feature_matches,
        )
        total = scoring.candidate_total_score(feature_matches)
        return Candidate(
            rank=0,
            company=company,
            product=product,
            aliases=aliases,
            score=total,
            hard_rule_check=hard,
            feature_match_table=feature_matches,
            main_evidence_urls=evidence_url_set,
            remaining_gaps=data.get("remaining_gaps", []) or [],
            reason_for_top5=str(data.get("reason_for_top5", "")).strip(),
        )


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
