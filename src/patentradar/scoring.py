"""硬性规则与计分规则（PRD §9 / §10）。"""

from __future__ import annotations

from .dates import is_after_application
from .schemas import (
    Candidate,
    ClaimFeature,
    FeatureMatch,
    HardRuleCheck,
    Judgement,
)

JUDGEMENT_SCORE: dict[Judgement, float] = {
    "明确满足": 1.0,
    "可能满足": 0.8,
    "证据不足": 0.3,
    "明确不满足": 0.0,
}


def candidate_total_score(
    matches: list[FeatureMatch],
    *,
    feature_ids: list[str] | None = None,
) -> float:
    """PRD §10.3: 候选得分 = 各特征得分之和 / 特征总数 × 100。"""
    if not matches and not feature_ids:
        return 0.0
    by_id = {m.feature_id: m for m in matches}
    if feature_ids:
        total = sum(by_id.get(fid).score if fid in by_id else JUDGEMENT_SCORE["证据不足"]
                    for fid in feature_ids)
        return round(total / len(feature_ids) * 100, 2)
    total = sum(m.score for m in matches)
    return round(total / len(matches) * 100, 2)


def normalize_feature_matches(
    matches: list[FeatureMatch],
    claim_features: list[ClaimFeature],
) -> list[FeatureMatch]:
    """补齐并校正候选的逐项特征表。

    LLM 偶尔会漏掉难判断特征，或返回与 judgement 不一致的 score。这里做代码级
    兜底：按权利要求 1 的特征顺序输出完整表；缺失项统一按"证据不足"计 0.3；
    无 URL 证据的强判断降级为"证据不足"；"可能满足"必须有 URL 证据和推理链。
    """
    raw_by_id: dict[str, FeatureMatch] = {}
    valid_ids = {f.feature_id for f in claim_features}
    for m in matches:
        if m.feature_id in valid_ids and m.feature_id not in raw_by_id:
            raw_by_id[m.feature_id] = m

    normalized: list[FeatureMatch] = []
    for cf in claim_features:
        m = raw_by_id.get(cf.feature_id)
        if m is None:
            normalized.append(FeatureMatch(
                feature_id=cf.feature_id,
                claim_feature=cf.feature_text,
                judgement="证据不足",
                score=JUDGEMENT_SCORE["证据不足"],
                reasoning="LLM 未返回该特征判断，按证据不足处理。",
                evidence=[],
            ))
            continue

        judgement = m.judgement
        reasoning = (m.reasoning or "").strip()
        has_url_evidence = any(ev.url for ev in m.evidence)
        downgrade_reason: str | None = None
        if judgement in {"明确满足", "明确不满足"} and not has_url_evidence:
            downgrade_reason = "缺少公开证据 URL，按证据不足处理。"
        elif judgement == "可能满足" and not has_url_evidence:
            downgrade_reason = "可能满足缺少公开证据 URL，按证据不足处理。"
        elif judgement == "可能满足" and not reasoning:
            downgrade_reason = "可能满足缺少推理链，按证据不足处理。"

        if downgrade_reason:
            judgement = "证据不足"
            reasoning = f"{reasoning} {downgrade_reason}".strip()

        normalized.append(FeatureMatch(
            feature_id=cf.feature_id,
            claim_feature=m.claim_feature or cf.feature_text,
            judgement=judgement,  # type: ignore[arg-type]
            score=JUDGEMENT_SCORE[judgement],
            reasoning=reasoning,
            evidence=m.evidence,
        ))
    return normalized


def has_clearly_unmatched(matches: list[FeatureMatch]) -> bool:
    return any(m.judgement == "明确不满足" for m in matches)


# PRD §9.1：模糊或占位字段不算"明确"。
# 中文用子串匹配（中文短词不易误伤）；英文用整词匹配（避免 "na" 误命中 "synaptics" 这类）。
_INVALID_CN = (
    "未知", "不明", "未明", "未公开", "暂无", "无法确认", "未找到",
    "未指明", "未提及", "尚不清楚", "尚未公开",
)
_INVALID_EN = {"na", "unknown", "none", "null", "tbd"}

import re as _re
_WORD_RE = _re.compile(r"[a-z]+")


def _looks_clear(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if any(tok in name for tok in _INVALID_CN):
        return False
    if "n/a" in name.lower():
        return False
    eng_words = set(_WORD_RE.findall(name.lower()))
    if eng_words and eng_words.issubset(_INVALID_EN):
        return False
    return True


def evaluate_hard_rules(
    *,
    company: str,
    product: str,
    assignees: list[str],
    evidence_urls: list[str],
    feature_matches: list[FeatureMatch],
    patent_application_date: str | None = None,
    product_launch_date: str | None = None,
) -> HardRuleCheck:
    """对一个候选执行 PRD §9 排除规则的可机读检查。"""
    is_owner = _is_patent_owner(company, assignees)
    launch_after_application = is_after_application(
        product_launch_date,
        patent_application_date,
    )
    return HardRuleCheck(
        is_patent_owner_product=is_owner,
        has_clear_company=_looks_clear(company),
        has_clear_product=_looks_clear(product),
        has_public_evidence=bool(evidence_urls),
        has_any_clearly_unmatched_feature=has_clearly_unmatched(feature_matches),
        patent_application_date=patent_application_date,
        product_launch_date=product_launch_date,
        product_launch_after_application=launch_after_application,
    )


def passes_hard_rules(check: HardRuleCheck) -> tuple[bool, str | None]:
    """PRD §9.1：返回 (是否通过, 不通过原因)。"""
    if check.is_patent_owner_product:
        return False, "专利权人/关联主体自身产品"
    if not check.has_clear_company:
        return False, "无明确公司/品牌"
    if not check.has_clear_product:
        return False, "无明确产品名/型号"
    if not check.has_public_evidence:
        return False, "无任何公开证据 URL"
    if check.product_launch_after_application is False:
        return False, (
            "竞品上市/发布/量产日期不晚于专利申请日"
            f"（竞品: {check.product_launch_date or '未知'}；申请日: "
            f"{check.patent_application_date or '未知'}）"
        )
    if check.has_any_clearly_unmatched_feature:
        return False, "存在明确不满足的必要技术特征"
    return True, None


# PRD §10.4 同分排序
SOURCE_RELIABILITY_RANK = {"high": 3, "medium": 2, "low": 1}


def tiebreak_key(c: Candidate, *, sources_count: int = 1) -> tuple:
    """同分排序 key（数值越大越优）。"""
    n_official = sum(
        1
        for fm in c.feature_match_table
        for ev in fm.evidence
        if ev.source_reliability == "high"
    )
    has_model = 1 if any(ch.isdigit() for ch in c.product) else 0
    n_features_with_evidence = sum(1 for fm in c.feature_match_table if fm.evidence)
    avg_reliability = (
        sum(SOURCE_RELIABILITY_RANK.get(e.source_reliability, 0)
            for fm in c.feature_match_table for e in fm.evidence) /
        max(1, sum(len(fm.evidence) for fm in c.feature_match_table))
    )
    return (n_official, has_model, n_features_with_evidence, sources_count, avg_reliability)


def _is_patent_owner(company: str, assignees: list[str]) -> bool:
    """松匹配：公司名包含或被包含于专利权人；忽略大小写 / 空白 / 公司类型后缀。"""
    if not company or not assignees:
        return False
    norm = lambda s: "".join(  # noqa: E731
        ch for ch in s.lower()
        if ch.isalnum()
    )
    nc = norm(company)
    for a in assignees:
        na = norm(a)
        if not na or not nc:
            continue
        # 短名包含于长名（如 "BYD" ⊂ "BYD Semiconductor"）
        if nc in na or na in nc:
            return True
    return False
