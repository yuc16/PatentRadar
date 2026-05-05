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

from .. import prompts
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

    top5: list[FinalCandidate] = []
    for i, raw in enumerate(payload.get("top5", []) or [], start=1):
        if not isinstance(raw, dict):
            continue
        fmt = _build_feature_matches(raw.get("final_feature_table"))
        score = float(raw.get("score") or 0)
        risk = str(raw.get("risk_level") or "弱相关").strip()
        if risk not in {"高度疑似落入", "中度疑似", "局部相似", "弱相关"}:
            risk = _risk_from_score(score, fmt)
        top5.append(FinalCandidate(
            rank=i,
            candidate_id=str(raw.get("candidate_id", "")).strip() or f"M{i:03d}",
            company=str(raw.get("company", "")).strip(),
            product=str(raw.get("product", "")).strip(),
            aliases=[str(a) for a in (raw.get("aliases") or [])],
            score=round(score, 1),
            risk_level=risk,  # type: ignore[arg-type]
            final_feature_table=fmt,
            main_evidence_urls=[str(u) for u in (raw.get("main_evidence_urls") or [])],
            reason_for_top5=str(raw.get("reason_for_top5", "")).strip(),
            remaining_gaps=raw.get("remaining_gaps") or [],
        ))

    excluded = [
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

    return FinalReport(
        patent_publication_no=task.patent.publication_no,
        claim_1_text=task.claim_1_text,
        claim_features=task.claim_features,
        top5=top5,
        excluded=excluded,
        needs_manual_review=needs,
        reviewer_model=f"codex:{model}",
        elapsed_seconds=round(time.monotonic() - t0, 2),
        notes=str(payload.get("notes", "")).strip(),
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
