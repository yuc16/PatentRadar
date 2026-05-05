"""硬性规则与计分规则（PRD §9 / §10）。"""

from __future__ import annotations

from .schemas import (
    Candidate,
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


def candidate_total_score(matches: list[FeatureMatch]) -> float:
    """PRD §10.3: 候选得分 = 各特征得分之和 / 特征总数 × 100。"""
    if not matches:
        return 0.0
    total = sum(m.score for m in matches)
    return round(total / len(matches) * 100, 2)


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
) -> HardRuleCheck:
    """对一个候选执行 PRD §9 排除规则的可机读检查。"""
    is_owner = _is_patent_owner(company, assignees)
    return HardRuleCheck(
        is_patent_owner_product=is_owner,
        has_clear_company=_looks_clear(company),
        has_clear_product=_looks_clear(product),
        has_public_evidence=bool(evidence_urls),
        has_any_clearly_unmatched_feature=has_clearly_unmatched(feature_matches),
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
