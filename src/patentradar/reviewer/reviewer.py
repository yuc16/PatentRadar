"""GPT-5.5 最终复核（PRD §11）。

接收三个 Agent 的原始输出（list[AgentOutput]）+ task_package，平铺所有候选 +
其完整证据，让 GPT-5.5 在一次调用中完成：
  1. 跨候选合并去重（同公司不同名 / 同产品不同型号）
  2. 证据真实性校验
  3. 重新打分 + 风险等级判定
  4. 输出 Top5 + 排除清单 + 人工复查清单

不再依赖代码层的 token 归一化合并 —— 由 GPT-5.5 自己判断同义。
"""

from __future__ import annotations

import os
import time
import logging

from .. import prompts, scoring
from ..agents.base import _normalize_reliability, _normalize_source_type
from ..llm import codex
from ..schemas import (
    AgentOutput,
    Candidate,
    Evidence,
    FeatureMatch,
    FinalCandidate,
    FinalReport,
    NeedsManualReview,
    ReviewExcluded,
    TaskPackage,
)
from ..search import pool

logger = logging.getLogger("patentradar.reviewer")

REVIEW_SUPPLEMENT_MAX_CANDIDATES = 15
REVIEW_SUPPLEMENT_FEATURES_PER_CANDIDATE = 4
REVIEW_SUPPLEMENT_HITS_PER_FEATURE = 2
REVIEW_SUPPLEMENT_SUMMARY_CHARS = 1200


def _format_features_block(task: TaskPackage) -> str:
    return "\n".join(
        f"- {f.feature_id} (essential={f.is_essential}): {f.feature_text}"
        for f in task.claim_features
    )


def _format_one_candidate(agent_name: str, idx: int, c: Candidate) -> str:
    """把单个 Agent Top 候选格式化为给 GPT-5.5 看的文本块。"""
    parts = [f"━━━ raw_id={agent_name}#{idx}  来源 Agent: {agent_name} ━━━"]
    parts.append(f"公司: {c.company}")
    parts.append(f"产品: {c.product}")
    if c.aliases:
        parts.append(f"别名: {', '.join(c.aliases)}")
    parts.append(f"该 Agent 给出的初步分数: {c.score}")
    if c.reason_for_top5:
        parts.append(f"该 Agent 入选理由: {c.reason_for_top5[:200]}")

    parts.append("\n[证据]")
    seen_urls: set[str] = set()
    for fm in c.feature_match_table:
        for ev in fm.evidence:
            if not ev.url or ev.url in seen_urls:
                continue
            seen_urls.add(ev.url)
            parts.append(
                f"  • 来源类型={ev.source_type}({ev.source_reliability})"
            )
            parts.append(f"    URL: {ev.url}")
            parts.append(f"    标题: {ev.title}")
            if ev.summary:
                parts.append(f"    摘要: {ev.summary[:300]}")
            if ev.supported_features:
                parts.append(f"    支撑特征: {', '.join(ev.supported_features)}")
    if not seen_urls:
        parts.append("  (无证据)")

    parts.append("\n[该 Agent 的特征判断]")
    for fm in c.feature_match_table:
        ev_count = len([e for e in fm.evidence if e.url])
        rea = (fm.reasoning or "").replace("\n", " ")
        if len(rea) > 180:
            rea = rea[:180] + "…"
        parts.append(f"  {fm.feature_id}: {fm.judgement}({fm.score}) ev={ev_count}  推理: {rea}")
    parts.append("")
    return "\n".join(parts)


def _format_candidates_block(agent_outputs: list[AgentOutput]) -> tuple[str, int]:
    blocks: list[str] = []
    n = 0
    for ao in agent_outputs:
        for i, c in enumerate(ao.top5_candidates, start=1):
            blocks.append(_format_one_candidate(ao.agent_name, i, c))
            n += 1
    return "\n".join(blocks), n


def review_agent_outputs(
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
    *,
    reasoning_effort: str = "medium",
) -> FinalReport:
    """主入口：直接接收三 Agent 输出，平铺给 GPT-5.5。"""
    t0 = time.monotonic()
    model = (os.getenv("REVIEWER_MODEL") or "gpt-5.5").strip()

    agent_outputs, supplement_count = _supplement_agent_outputs(agent_outputs, task)
    candidates_block, n_candidates = _format_candidates_block(agent_outputs)

    system = prompts.load("reviewer_system")
    user = prompts.render(
        "reviewer_user",
        pub_no=task.patent.publication_no,
        title=task.patent.title or "(未知)",
        assignees=", ".join(task.patent.assignees) or "(未知)",
        claim_1_text=task.claim_1_text,
        features_block=_format_features_block(task),
        n_candidates=n_candidates,
        candidates_block=candidates_block,
    )

    payload = codex.chat_json(
        system=system,
        user_text=user,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
    )

    feature_text_by_id = {f.feature_id: f.feature_text for f in task.claim_features}

    # 收集所有原始 evidence URL，用于回填候选 evidence 时找原数据（避免 GPT-5.5 漏字段）
    evidence_lookup: dict[str, Evidence] = {}
    for ao in agent_outputs:
        for c in ao.top5_candidates:
            for fm in c.feature_match_table:
                for ev in fm.evidence:
                    if ev.url and ev.url not in evidence_lookup:
                        evidence_lookup[ev.url] = ev

    def _build_evidence(raw_list):
        out: list[Evidence] = []
        for re_ev in raw_list or []:
            if not isinstance(re_ev, dict):
                continue
            url = str(re_ev.get("url", "")).strip()
            if not url or url not in evidence_lookup:
                if url:
                    logger.info("丢弃未出现在复核输入中的证据 URL: %s", url[:80])
                continue
            ref = evidence_lookup.get(url)
            out.append(Evidence(
                url=url,
                title=str(re_ev.get("title") or (ref.title if ref else "")).strip(),
                source_type=_normalize_source_type(
                    re_ev.get("source_type") or (ref.source_type if ref else None)
                ),
                source_reliability=_normalize_reliability(
                    re_ev.get("source_reliability") or (ref.source_reliability if ref else None)
                ),
                summary=str(re_ev.get("summary") or (ref.summary if ref else "")).strip(),
                supported_features=[str(s) for s in (re_ev.get("supported_features") or [])],
            ))
        return out

    def _build_feature_matches(raw_list):
        from ..scoring import JUDGEMENT_SCORE
        out: list[FeatureMatch] = []
        for raw in raw_list or []:
            if not isinstance(raw, dict):
                continue
            fid = str(raw.get("feature_id", "")).strip()
            judg = str(raw.get("judgement", "证据不足")).strip()
            if judg not in JUDGEMENT_SCORE:
                judg = "证据不足"
            out.append(FeatureMatch(
                feature_id=fid,
                claim_feature=feature_text_by_id.get(fid, ""),
                judgement=judg,  # type: ignore[arg-type]
                score=JUDGEMENT_SCORE[judg],
                reasoning=str(raw.get("reasoning", "")).strip(),
                evidence=_build_evidence(raw.get("evidence")),
            ))
        return out

    auto_excluded: list[ReviewExcluded] = []
    top5: list[FinalCandidate] = []
    for raw in payload.get("top5", []) or []:
        if not isinstance(raw, dict):
            continue
        fmt = scoring.normalize_feature_matches(
            _build_feature_matches(raw.get("final_feature_table")),
            task.claim_features,
        )
        score = scoring.candidate_total_score(
            fmt,
            feature_ids=[f.feature_id for f in task.claim_features],
        )
        risk = _risk_from_score(score, fmt)
        raw_main_urls = {
            str(u) for u in (raw.get("main_evidence_urls") or [])
            if str(u) in evidence_lookup
        }
        evidence_urls = sorted({
            ev.url for fm in fmt for ev in fm.evidence if ev.url
        } | raw_main_urls)
        company = str(raw.get("company", "")).strip()
        product = str(raw.get("product", "")).strip()
        hard = scoring.evaluate_hard_rules(
            company=company,
            product=product,
            assignees=task.patent.assignees,
            evidence_urls=evidence_urls,
            feature_matches=fmt,
        )
        ok, reason = scoring.passes_hard_rules(hard)
        if not ok:
            auto_excluded.append(ReviewExcluded(
                candidate_id=str(raw.get("candidate_id", "")).strip(),
                company=company,
                product=product,
                discard_reason=reason or "最终复核代码校验未通过",
                evidence_urls=evidence_urls,
            ))
            continue
        top5.append(FinalCandidate(
            rank=len(top5) + 1,
            candidate_id=str(raw.get("candidate_id", "")).strip() or f"M{len(top5)+1:03d}",
            company=company,
            product=product,
            aliases=[str(a) for a in (raw.get("aliases") or [])],
            score=round(score, 1),
            risk_level=risk,  # type: ignore[arg-type]
            final_feature_table=fmt,
            main_evidence_urls=evidence_urls,
            reason_for_top5=str(raw.get("reason_for_top5", "")).strip(),
            remaining_gaps=raw.get("remaining_gaps") or [],
        ))
        if len(top5) >= 5:
            break

    excluded = auto_excluded + [
        ReviewExcluded(
            candidate_id=str(x.get("candidate_id", "")),
            company=str(x.get("company", "")),
            product=str(x.get("product", "")),
            discard_reason=str(x.get("discard_reason", "")),
            evidence_urls=[str(u) for u in (x.get("evidence_urls") or [])],
        )
        for x in (payload.get("excluded") or []) if isinstance(x, dict)
    ]
    needs = [
        NeedsManualReview(
            candidate_id=str(x.get("candidate_id", "")),
            company=str(x.get("company", "")),
            product=str(x.get("product", "")),
            gap=str(x.get("gap", "")),
            suggested_search_direction=str(x.get("suggested_search_direction", "")),
        )
        for x in (payload.get("needs_manual_review") or []) if isinstance(x, dict)
    ]

    notes = str(payload.get("notes", "")).strip()
    if supplement_count:
        supplement_note = f"最终复核前已执行代码侧补搜，新增 {supplement_count} 条证据线索。"
        notes = f"{notes} {supplement_note}".strip()

    return FinalReport(
        patent_publication_no=task.patent.publication_no,
        claim_1_text=task.claim_1_text,
        claim_features=task.claim_features,
        top5=top5,
        excluded=excluded,
        needs_manual_review=needs,
        reviewer_model=f"codex:{model}",
        elapsed_seconds=round(time.monotonic() - t0, 2),
        notes=notes,
    )


# 兼容旧导入名（有些下游代码仍可能用 review_candidate_pool）
def review_candidate_pool(_pool, task, *, reasoning_effort: str = "medium"):
    """兼容入口 — 内部已不依赖 candidate_pool；新代码请用 ``review_agent_outputs``。"""
    raise RuntimeError(
        "review_candidate_pool 已废弃。请改用 review_agent_outputs(list[AgentOutput], task)。"
    )


def _risk_from_score(score: float, fmt: list[FeatureMatch]) -> str:
    has_clearly_unmatched = any(m.judgement == "明确不满足" for m in fmt)
    if score >= 85 and not has_clearly_unmatched:
        return "高度疑似落入"
    if score >= 70:
        return "中度疑似"
    if score >= 50:
        return "局部相似"
    return "弱相关"


def _supplement_agent_outputs(
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
) -> tuple[list[AgentOutput], int]:
    """最终复核前对证据不足项执行代码侧补搜。"""
    outputs = [ao.model_copy(deep=True) for ao in agent_outputs]
    added = 0
    seen_candidates = 0
    for ao in outputs:
        for cand in ao.top5_candidates:
            if seen_candidates >= REVIEW_SUPPLEMENT_MAX_CANDIDATES:
                return outputs, added
            seen_candidates += 1
            cand.feature_match_table = scoring.normalize_feature_matches(
                cand.feature_match_table,
                task.claim_features,
            )
            cand.score = scoring.candidate_total_score(
                cand.feature_match_table,
                feature_ids=[f.feature_id for f in task.claim_features],
            )
            added += _supplement_candidate(cand, task)
    return outputs, added


def _supplement_candidate(cand: Candidate, task: TaskPackage) -> int:
    existing_urls = {
        ev.url
        for fm in cand.feature_match_table
        for ev in fm.evidence
        if ev.url
    } | set(cand.main_evidence_urls)
    gap_ids = {
        str(g.get("feature_id", "")).strip()
        for g in cand.remaining_gaps
        if isinstance(g, dict)
    }
    target_features = [
        fm for fm in cand.feature_match_table
        if (
            fm.judgement == "证据不足"
            or not any(ev.url for ev in fm.evidence)
            or fm.feature_id in gap_ids
        )
    ][:REVIEW_SUPPLEMENT_FEATURES_PER_CANDIDATE]

    added = 0
    feature_by_id = {f.feature_id: f for f in task.claim_features}
    for fm in target_features:
        cf = feature_by_id.get(fm.feature_id)
        if cf is None:
            continue
        query = _review_supplement_query(cand.company, cand.product, cf)
        try:
            hits = pool.search(
                query,
                engines=pool.DEFAULT_SEARCH_ENGINES,
                num_per_engine=REVIEW_SUPPLEMENT_HITS_PER_FEATURE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("review supplement search failed %r: %s", query, exc)
            continue
        for hit in hits[:REVIEW_SUPPLEMENT_HITS_PER_FEATURE]:
            if not hit.url or hit.url in existing_urls:
                continue
            evidence = _evidence_from_hit(hit, fm.feature_id)
            fm.evidence.append(evidence)
            cand.main_evidence_urls.append(hit.url)
            existing_urls.add(hit.url)
            added += 1
    if added:
        cand.main_evidence_urls = sorted(set(cand.main_evidence_urls))
    return added


def _review_supplement_query(company: str, product: str, feature) -> str:
    terms: list[str] = []
    terms.extend(feature.marketing_terms[:2])
    terms.extend(feature.engineering_terms[:3])
    if "公式" in feature.feature_text or "$" in feature.feature_text:
        terms.extend(["算法", "SDK", "校准", "补偿"])
    if not terms:
        terms.append(feature.feature_text[:80])
    return " ".join(
        part for part in [company, product, *terms[:5], "规格书 OR 产品手册 OR 白皮书 OR datasheet"]
        if part
    ).strip()


def _evidence_from_hit(hit, feature_id: str) -> Evidence:
    text = hit.snippet or ""
    title = hit.title or ""
    try:
        page = pool.read_url(hit.url)
        text = page.text or text
        title = page.title or title
    except Exception as exc:  # noqa: BLE001
        logger.info("review supplement read failed %s: %s", hit.url[:80], exc)
    return Evidence(
        url=hit.url,
        title=title,
        source_type=_guess_source_type(hit.url, title),
        source_reliability=_guess_reliability(hit.url),
        summary=("[最终复核补搜] " + text[:REVIEW_SUPPLEMENT_SUMMARY_CHARS]).strip(),
        supported_features=[feature_id],
    )


def _guess_source_type(url: str, title: str) -> str:
    low = f"{url} {title}".lower()
    if ".pdf" in low:
        return "官方PDF"
    if "cninfo.com.cn" in low or "static.cninfo.com.cn" in low:
        return "年报"
    if "datasheet" in low or "数据手册" in title:
        return "产品手册"
    return "其他"


def _guess_reliability(url: str) -> str:
    low = url.lower()
    if ".pdf" in low or "cninfo.com.cn" in low:
        return "high"
    if any(x in low for x in ("weixin", "zhihu", "csdn", "blog")):
        return "low"
    return "medium"
