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

import json
import hashlib
import os
import re
import time
import logging
from pathlib import Path
from typing import Any

from .. import evidence as evidence_strategy, prompts, scoring
from ..agents.base import _normalize_reliability, _normalize_source_type
from ..dates import normalize_date_string
from ..llm import controller
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
from ..search.session import SearchSession

logger = logging.getLogger("patentradar.reviewer")


REVIEW_SUPPLEMENT_MAX_CANDIDATES = 15
REVIEW_SUPPLEMENT_FEATURES_PER_CANDIDATE = 4
REVIEW_SUPPLEMENT_TARGETS_PER_CANDIDATE = 3
REVIEW_SUPPLEMENT_QUERIES_PER_TARGET = 2
REVIEW_SUPPLEMENT_HITS_PER_FEATURE = 3
REVIEW_SUPPLEMENT_SUMMARY_CHARS = 1000
REVIEW_SUPPLEMENT_ENGINES = pool.DEFAULT_SEARCH_ENGINES


def _review_engines_for_target(target: evidence_strategy.EvidenceTarget) -> tuple[str, ...]:
    if target.target_id == "market_date":
        return ("bocha", "tavily", "brave_news")
    if target.target_id == "spec":
        return ("tavily", "brave", "exa")
    if target.target_id in {"structure", "algorithm", "product_docs"}:
        return ("tavily", "exa", "brave")
    return REVIEW_SUPPLEMENT_ENGINES


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
    if c.product_launch_date:
        parts.append(
            f"公开上市/发布/量产日期: {c.product_launch_date}"
            + (
                f"（证据: {c.product_launch_date_evidence_url}）"
                if c.product_launch_date_evidence_url else ""
            )
        )
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
            tier = evidence_strategy.tier_label(ev.url, ev.title)
            parts.append(
                f"  • 来源类型={ev.source_type}({ev.source_reliability}) / {tier}"
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


def _candidate_key(company: str, product: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", f"{company}{product}".lower())


def _lookup_launch_date(
    launch_lookup: dict[str, tuple[str | None, str | None]],
    company: str,
    product: str,
) -> tuple[str | None, str | None]:
    key = _candidate_key(company, product)
    if key in launch_lookup:
        return launch_lookup[key]
    for raw_key, value in launch_lookup.items():
        if key and raw_key and (key in raw_key or raw_key in key):
            return value
    return None, None


_MODEL_HARD_EXCLUDE_MARKERS = (
    "专利权人",
    "关联主体",
    "无明确公司",
    "无明确产品",
    "无任何公开证据",
    "无公开证据",
    "没有任何公开证据",
    "未提供任何公开证据",
    "明确不满足",
    "不满足",
    "低于",
    "高于",
    "不晚于专利申请日",
    "早于专利申请日",
)


def _is_model_hard_exclusion(reason: str) -> bool:
    """模型 excluded 只接受真正硬规则；证据缺口类原因转人工复查。"""
    reason = (reason or "").strip()
    if not reason:
        return False
    return any(marker in reason for marker in _MODEL_HARD_EXCLUDE_MARKERS)


def _candidate_signature(company: str, product: str, aliases: list[str] | None = None) -> str:
    values = [company, product, *(aliases or [])]
    return _candidate_key("", " ".join(v for v in values if v))


def _has_meaningful_overlap(a: str, b: str, *, min_len: int = 3) -> bool:
    if len(a) < min_len or len(b) < min_len:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    for size in range(len(shorter), min_len - 1, -1):
        for start in range(0, len(shorter) - size + 1):
            part = shorter[start:start + size]
            if part in longer:
                return True
    return False


def _is_same_candidate(
    *,
    company: str,
    product: str,
    aliases: list[str] | None,
    other_company: str,
    other_product: str,
    other_aliases: list[str] | None = None,
) -> bool:
    company_key = _candidate_key(company, "")
    other_company_key = _candidate_key(other_company, "")
    if not company_key or not other_company_key:
        return False
    same_company = (
        company_key in other_company_key
        or other_company_key in company_key
        or _has_meaningful_overlap(company_key, other_company_key)
    )
    if not same_company:
        for alias in aliases or []:
            alias_key = _candidate_key(alias, "")
            if len(alias_key) >= 3 and (
                alias_key in other_company_key or other_company_key in alias_key
            ):
                same_company = True
                break
    if not same_company:
        for alias in other_aliases or []:
            alias_key = _candidate_key(alias, "")
            if len(alias_key) >= 3 and (
                alias_key in company_key or company_key in alias_key
            ):
                same_company = True
                break
    if not same_company:
        return False

    def model_ids(*values: str) -> set[str]:
        text = " ".join(v for v in values if v)
        ids = {m.group(1).lower().replace(" ", "") for m in re.finditer(r"(?i)\b(\d{2,4}\s?ah)\b", text)}
        ids |= {m.group(1).lower() for m in re.finditer(r"(?i)\b(L\d{3,4})\b", text)}
        return ids

    ids = model_ids(product, *(aliases or []))
    other_ids = model_ids(other_product, *(other_aliases or []))
    if ids and other_ids and ids.isdisjoint(other_ids):
        return False

    product_keys = [
        _candidate_key("", product),
        *(_candidate_key("", a) for a in (aliases or [])),
    ]
    other_product_keys = [
        _candidate_key("", other_product),
        *(_candidate_key("", a) for a in (other_aliases or [])),
    ]
    product_keys = [p for p in product_keys if len(p) >= 3]
    other_product_keys = [p for p in other_product_keys if len(p) >= 3]
    return any(
        a == b or a in b or b in a
        for a in product_keys
        for b in other_product_keys
    )


def _clean_aliases_for_product(product: str, aliases: list[str] | None) -> list[str]:
    """Remove aliases that clearly describe a different concrete model."""
    product_low = product.lower()
    product_caps = {m.group(1).lower() for m in re.finditer(r"(?i)\b(\d{2,4}\s?ah)\b", product)}
    product_l_models = {m.group(1).lower() for m in re.finditer(r"(?i)\b(L\d{3,4})\b", product)}
    cleaned: list[str] = []
    seen: set[str] = set()
    for alias in aliases or []:
        alias = str(alias).strip()
        if not alias:
            continue
        alias_key = _candidate_key("", alias)
        if alias_key in seen:
            continue
        alias_caps = {m.group(1).lower() for m in re.finditer(r"(?i)\b(\d{2,4}\s?ah)\b", alias)}
        if product_caps and alias_caps and alias_caps.isdisjoint(product_caps):
            continue
        alias_l_models = {m.group(1).lower() for m in re.finditer(r"(?i)\b(L\d{3,4})\b", alias)}
        if alias_l_models and (
            not product_l_models
            or alias_l_models.isdisjoint(product_l_models)
        ):
            # Avoid treating a series/model like L600 as an alias of a capacity-named cell
            # such as 184Ah unless the product itself is named as that L-series model.
            if not any(model in product_low for model in alias_l_models):
                continue
        cleaned.append(alias)
        seen.add(alias_key)
    return cleaned


def _refine_product_scope(company: str, product: str, aliases: list[str] | None) -> str:
    """Prefer a concrete product/model over a broad series label when available."""
    product = str(product or "").strip()
    if not product:
        return product
    broad = any(marker in product for marker in ("系列", "全系", "含", "等型号", "L300-L600"))
    if not broad:
        return product

    candidates: list[str] = []
    for alias in aliases or []:
        alias = str(alias).strip()
        if not alias:
            continue
        low = alias.lower()
        if "系列" in alias or "全系" in alias or re.search(r"(?i)\bL\d{3,4}\b", alias):
            continue
        if not re.search(r"(?i)\b\d{2,4}\s?ah\b", alias):
            continue
        if not any(term in low or term in alias for term in ("battery", "cell", "电池", "电芯", "blade", "刀片", "短刀")):
            continue
        candidates.append(alias)

    if not candidates:
        return product

    def _score(alias: str) -> tuple[int, int]:
        low = alias.lower()
        score = 0
        if "lifepo4" in low:
            score += 3
        if "blade" in low or "刀片" in alias or "短刀" in alias:
            score += 3
        if "battery" in low:
            score += 1
        if "cell" in low or "电芯" in alias:
            score += 1
        return score, len(alias)

    best = max(candidates, key=_score)
    company_low = company.lower()
    if ("蜂巢" in company or "svolt" in company_low) and not best.lower().startswith("svolt"):
        best = f"SVOLT {best}"
    if "battery" in best.lower() and "cell" not in best.lower() and "电芯" not in best:
        best = f"{best} Cell"
    return best


def _trim_scope_conflicts(text: str, product: str) -> str:
    """Remove claims about other concrete models from a narrowed product rationale."""
    if re.search(r"(?i)\bL\d{3,4}\b", product):
        return text
    text = re.sub(r"，?L\d{3,4}型号长度约\d+(?:\.\d+)?\s*mm", "", text)
    text = text.replace("，均明确落入", "，明确落入")
    text = text.replace("均明确落入", "明确落入")
    return text


def _apply_product_scope_cleanup(candidate: FinalCandidate) -> FinalCandidate:
    product = _refine_product_scope(candidate.company, candidate.product, candidate.aliases)
    candidate.product = product
    candidate.aliases = _clean_aliases_for_product(product, candidate.aliases)
    for fm in candidate.final_feature_table:
        fm.reasoning = _trim_scope_conflicts(fm.reasoning, product)
    return candidate


def _evidence_text(ev: Evidence) -> str:
    return f"{ev.title}\n{ev.summary}".lower()


def _extract_rect_dimensions_mm(text: str) -> tuple[float, float, float] | None:
    normalized = (
        text.replace("×", "x")
        .replace("*", "x")
        .replace("\\", "x")
        .replace("/", "x")
    )
    patterns = [
        r"(?:dimension|dimensions|size|尺寸|外形尺寸)[^0-9]{0,80}"
        r"(\d{2,4}(?:\.\d+)?)\s*x\s*(\d{2,4}(?:\.\d+)?)\s*x\s*(\d{1,4}(?:\.\d+)?)\s*mm",
        r"(\d{2,4}(?:\.\d+)?)\s*x\s*(\d{2,4}(?:\.\d+)?)\s*x\s*(\d{1,4}(?:\.\d+)?)\s*mm",
    ]
    for pattern in patterns:
        m = re.search(pattern, normalized, flags=re.I | re.S)
        if m:
            values = tuple(float(x) for x in m.groups())
            if min(values) > 0 and max(values) / min(values) >= 3:
                return values  # type: ignore[return-value]

    labeled: dict[str, float] = {}
    for key, pattern in {
        "length": r"(?:length|长度|长)\D{0,30}(\d{2,4}(?:\.\d+)?)\s*(?:±\s*\d+(?:\.\d+)?)?\s*mm",
        "width": r"(?:width|宽度|宽|height|高度|高)\D{0,30}(\d{2,4}(?:\.\d+)?)\s*(?:±\s*\d+(?:\.\d+)?)?\s*mm",
        "thickness": r"(?:thickness|厚度|厚)\D{0,30}(\d{1,4}(?:\.\d+)?)\s*(?:±\s*\d+(?:\.\d+)?)?\s*mm",
    }.items():
        m = re.search(pattern, normalized, flags=re.I | re.S)
        if m:
            labeled[key] = float(m.group(1))
    if {"length", "width", "thickness"}.issubset(labeled):
        return labeled["length"], labeled["width"], labeled["thickness"]
    return None


def _extract_energy_wh(text: str) -> float | None:
    values: list[float] = []
    for m in re.finditer(
        r"(?:energy|放电能量|能量)\D{0,30}(\d{2,5}(?:\.\d+)?)\s*wh(?!\s*/\s*kg)",
        text,
        flags=re.I,
    ):
        values.append(float(m.group(1)))
    if values:
        return max(values)

    voltage = None
    capacity = None
    voltage_match = re.search(r"(\d(?:\.\d+)?)\s*v\b", text, flags=re.I)
    capacity_match = re.search(r"(\d{2,4}(?:\.\d+)?)\s*ah\b", text, flags=re.I)
    if voltage_match:
        voltage = float(voltage_match.group(1))
    if capacity_match:
        capacity = float(capacity_match.group(1))
    if voltage and capacity:
        return voltage * capacity
    return None


def _all_matching_candidate_evidence(
    final_candidate: FinalCandidate,
    agent_outputs: list[AgentOutput],
) -> list[Evidence]:
    evidence_by_url: dict[str, Evidence] = {}

    def add(ev: Evidence) -> None:
        if not ev.url:
            return
        existing = evidence_by_url.get(ev.url)
        if existing is None:
            evidence_by_url[ev.url] = ev.model_copy(deep=True)
            return
        if ev.title and ev.title not in existing.title:
            existing.title = f"{existing.title} / {ev.title}".strip(" /")
        if ev.summary and ev.summary not in existing.summary:
            existing.summary = f"{existing.summary}\n{ev.summary}".strip()
        existing.supported_features = list(dict.fromkeys([
            *existing.supported_features,
            *ev.supported_features,
        ]))

    for fm in final_candidate.final_feature_table:
        for ev in fm.evidence:
            add(ev)

    for ao in agent_outputs:
        for raw in ao.top5_candidates:
            if not _is_same_candidate(
                company=final_candidate.company,
                product=final_candidate.product,
                aliases=final_candidate.aliases,
                other_company=raw.company,
                other_product=raw.product,
                other_aliases=raw.aliases,
            ):
                continue
            for fm in raw.feature_match_table:
                for ev in fm.evidence:
                    add(ev)
    return list(evidence_by_url.values())


def _candidate_model_tokens(candidate: FinalCandidate) -> set[str]:
    text = " ".join([candidate.product, *candidate.aliases])
    tokens = {m.group(1).lower().replace(" ", "") for m in re.finditer(r"(?i)\b(\d{2,4}\s?ah)\b", text)}
    tokens |= {m.group(1).lower() for m in re.finditer(r"(?i)\b(L\d{3,4})\b", text)}
    return tokens


def _sort_evidence_for_model(candidate: FinalCandidate, evidence: list[Evidence]) -> list[Evidence]:
    tokens = _candidate_model_tokens(candidate)
    if not tokens:
        return evidence

    def score(ev: Evidence) -> tuple[int, int]:
        text = _evidence_text(ev).replace(" ", "")
        has_model = int(any(tok in text for tok in tokens))
        return has_model, len(text)

    return sorted(evidence, key=score, reverse=True)


def _apply_calculated_parameter_matches(
    top5: list[FinalCandidate],
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
) -> None:
    """Use public numeric parameters to fill formula features conservatively.

    This does not invent evidence. It only upgrades S/E-style formula features
    when existing public URLs for the same candidate expose three dimensions and
    either energy in Wh or capacity + voltage.
    """
    feature_ids = [f.feature_id for f in task.claim_features]
    for candidate in top5:
        evidence_pool = _sort_evidence_for_model(
            candidate,
            _all_matching_candidate_evidence(candidate, agent_outputs),
        )
        if not evidence_pool:
            continue
        dim_item: tuple[Evidence, tuple[float, float, float]] | None = None
        energy_item: tuple[Evidence, float] | None = None
        for ev in evidence_pool:
            text = _evidence_text(ev)
            dims = _extract_rect_dimensions_mm(text)
            energy = _extract_energy_wh(text)
            if dims and dim_item is None:
                dim_item = (ev, dims)
            if energy and energy_item is None:
                energy_item = (ev, energy)
            if dim_item and energy_item:
                break
        if not dim_item or not energy_item:
            continue

        dim_ev, dims = dim_item
        energy_ev, energy = energy_item
        a, b, c = dims
        surface = 2 * (a * b + a * c + b * c)
        ratio = surface / energy if energy else 0
        if ratio <= 0 or ratio > 1000:
            continue

        used_evidence = [dim_ev]
        if energy_ev.url != dim_ev.url:
            used_evidence.append(energy_ev)
        for fm in candidate.final_feature_table:
            claim_text = fm.claim_feature or ""
            if "S/E" not in claim_text and "表面积S与" not in claim_text:
                continue
            if fm.judgement == "明确不满足":
                continue
            if fm.judgement == "明确满足" and fm.evidence:
                continue
            fm.judgement = "可能满足"
            fm.score = scoring.JUDGEMENT_SCORE["可能满足"]
            fm.reasoning = (
                f"公开参数证据给出三维尺寸约 {a:g}×{b:g}×{c:g} mm，"
                f"并披露单体能量约 {energy:g} Wh（或可由容量和电压计算）。"
                f"据此表面积S≈{surface:,.0f} mm²，S/E≈{ratio:.1f} mm²/Wh，"
                "低于1000 mm²/Wh。该判断为基于公开参数的复核计算，按可能满足处理。"
            )
            fm.evidence = used_evidence
            known_urls = set(candidate.main_evidence_urls)
            for ev in used_evidence:
                if ev.url not in known_urls:
                    candidate.main_evidence_urls.append(ev.url)
                    known_urls.add(ev.url)
            candidate.remaining_gaps = [
                gap for gap in candidate.remaining_gaps
                if not (
                    isinstance(gap, dict)
                    and str(gap.get("feature_id", "")).strip() == fm.feature_id
                )
            ]
            candidate.score = round(
                scoring.candidate_total_score(
                    candidate.final_feature_table,
                    feature_ids=feature_ids,
                ),
                1,
            )
            candidate.risk_level = _risk_from_score(
                candidate.score,
                candidate.final_feature_table,
            )  # type: ignore[assignment]
            if "S/E" in candidate.reason_for_top5 or "表面积" in candidate.reason_for_top5:
                continue
            candidate.reason_for_top5 = (
                f"{candidate.reason_for_top5} 已基于公开参数补充核算S/E。"
            ).strip()


def _drop_resolved_manual_review_items(
    needs: list[NeedsManualReview],
    top5: list[FinalCandidate],
) -> list[NeedsManualReview]:
    by_id = {c.candidate_id: c for c in top5 if c.candidate_id}
    cleaned: list[NeedsManualReview] = []
    for item in needs:
        matched = by_id.get(item.candidate_id)
        if matched:
            unresolved = {
                str(g.get("feature_id", "")).strip()
                for g in matched.remaining_gaps
                if isinstance(g, dict)
            }
            if "F4" in item.gap and "F4" not in unresolved:
                continue
        cleaned.append(item)
    return cleaned


def _top5_already_has(
    top5: list[FinalCandidate],
    *,
    company: str,
    product: str,
    aliases: list[str] | None = None,
) -> bool:
    return any(
        _is_same_candidate(
            company=company,
            product=product,
            aliases=aliases,
            other_company=fc.company,
            other_product=fc.product,
            other_aliases=fc.aliases,
        )
        for fc in top5
    )


def _missing_feature_gaps(feature_matches: list[FeatureMatch]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for fm in feature_matches:
        if fm.judgement in {"证据不足", "可能满足"}:
            gaps.append({
                "feature_id": fm.feature_id,
                "gap": fm.reasoning or f"{fm.feature_id} 仍需补充公开证据核查。",
            })
    return gaps


def _dedupe_gaps(gaps: list[dict[str, Any]] | list[dict]) -> list[dict]:
    out: list[dict] = []
    seen_features: set[str] = set()
    seen_text: set[str] = set()
    for gap in gaps or []:
        if not isinstance(gap, dict):
            continue
        fid = str(gap.get("feature_id", "")).strip()
        text = str(gap.get("gap", "")).strip()
        key = (fid or "") + "|" + re.sub(r"\s+", "", text[:80])
        if fid and fid in seen_features:
            continue
        if key in seen_text:
            continue
        out.append(gap)
        if fid:
            seen_features.add(fid)
        seen_text.add(key)
    return out


def _candidate_evidence_urls(c: Candidate, feature_matches: list[FeatureMatch]) -> list[str]:
    urls = {
        str(u).strip()
        for u in (c.main_evidence_urls or [])
        if str(u).strip()
    }
    urls |= {
        ev.url
        for fm in feature_matches
        for ev in fm.evidence
        if ev.url
    }
    return sorted(urls)


def _fill_top5_from_agent_candidates(
    *,
    top5: list[FinalCandidate],
    excluded: list[ReviewExcluded],
    needs: list[NeedsManualReview],
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
) -> list[FinalCandidate]:
    """复核模型过度保守时，用 Agent 候选补足 Top5。

    只补入未触发代码硬规则的候选；证据不足保留为低分 / 待核查，不再丢弃。
    """
    feature_ids = [f.feature_id for f in task.claim_features]

    def already_listed(c: Candidate) -> bool:
        for fc in top5:
            if _is_same_candidate(
                company=c.company,
                product=c.product,
                aliases=c.aliases,
                other_company=fc.company,
                other_product=fc.product,
                other_aliases=fc.aliases,
            ):
                return True
        return False

    hard_excluded_signatures = {
        _candidate_signature(x.company, x.product)
        for x in excluded
        if _is_model_hard_exclusion(x.discard_reason)
    }
    manual_by_signature = {
        _candidate_signature(n.company, n.product): n
        for n in needs
    }

    raw_candidates: list[Candidate] = []
    seen_raw: set[str] = set()
    for ao in agent_outputs:
        for c in ao.top5_candidates:
            sig = _candidate_signature(c.company, c.product, c.aliases)
            if sig in seen_raw:
                continue
            seen_raw.add(sig)
            raw_candidates.append(c)

    raw_candidates.sort(
        key=lambda c: (c.score, *scoring.tiebreak_key(c)),
        reverse=True,
    )

    for c in raw_candidates:
        if len(top5) >= 5:
            break
        sig = _candidate_signature(c.company, c.product, c.aliases)
        if sig in hard_excluded_signatures or already_listed(c):
            continue

        fmt = scoring.normalize_feature_matches(c.feature_match_table, task.claim_features)
        evidence_urls = _candidate_evidence_urls(c, fmt)
        hard = scoring.evaluate_hard_rules(
            company=c.company,
            product=c.product,
            assignees=task.patent.assignees,
            evidence_urls=evidence_urls,
            feature_matches=fmt,
            patent_application_date=task.patent.application_date,
            product_launch_date=normalize_date_string(c.product_launch_date),
        )
        ok, _reason = scoring.passes_hard_rules(hard)
        if not ok:
            continue

        score = scoring.candidate_total_score(fmt, feature_ids=feature_ids)
        manual = manual_by_signature.get(sig)
        gaps = _dedupe_gaps(list(c.remaining_gaps or []) + _missing_feature_gaps(fmt))
        reason = c.reason_for_top5 or "Agent 给出公开证据线索，复核模型未纳入最终 Top5。"
        if manual and manual.gap:
            reason = f"{reason} 复核缺口：{manual.gap}"

        product = _refine_product_scope(c.company, c.product, c.aliases)
        aliases = _clean_aliases_for_product(product, c.aliases)
        top5.append(_apply_product_scope_cleanup(FinalCandidate(
            rank=len(top5) + 1,
            candidate_id=f"M{len(top5)+1:03d}",
            company=c.company,
            product=product,
            aliases=aliases,
            product_launch_date=normalize_date_string(c.product_launch_date),
            product_launch_date_evidence_url=c.product_launch_date_evidence_url,
            score=round(score, 1),
            risk_level=_risk_from_score(score, fmt),  # type: ignore[arg-type]
            final_feature_table=fmt,
            main_evidence_urls=evidence_urls,
            reason_for_top5=reason,
            remaining_gaps=gaps,
        )))

    for i, c in enumerate(top5, start=1):
        c.rank = i
    return top5


def review_agent_outputs(
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
    *,
    reasoning_effort: str = "medium",
    supplement_cache_path: str | Path | None = None,
    search_session: SearchSession | None = None,
) -> FinalReport:
    """主入口：直接接收三 Agent 输出，平铺给 GPT-5.5。"""
    t0 = time.monotonic()
    model = (os.getenv("REVIEWER_MODEL") or "gpt-5.5").strip()
    source_fingerprint = _agent_outputs_fingerprint(agent_outputs)

    cache_file = Path(supplement_cache_path) if supplement_cache_path else None
    cached = (
        _load_supplement_cache(cache_file, task, source_fingerprint)
        if cache_file
        else None
    )
    if cached is not None:
        agent_outputs, supplement_count = cached
    else:
        agent_outputs, supplement_count = _supplement_agent_outputs(
            agent_outputs,
            task,
            search_session=search_session or SearchSession(),
        )
        if cache_file:
            _write_supplement_cache(
                cache_file,
                agent_outputs,
                task,
                supplement_count,
                source_fingerprint,
            )
    candidates_block, n_candidates = _format_candidates_block(agent_outputs)

    system = prompts.load("reviewer_system")
    user = prompts.render(
        "reviewer_user",
        pub_no=task.patent.publication_no,
        title=task.patent.title or "(未知)",
        assignees=", ".join(task.patent.assignees) or "(未知)",
        application_date=task.patent.application_date or "(未知)",
        claim_1_text=task.claim_1_text,
        features_block=_format_features_block(task),
        n_candidates=n_candidates,
        candidates_block=candidates_block,
    )

    logger.info(
        "[reviewer] GPT-5.5 review START candidates=%d supplement_urls=%d",
        n_candidates, supplement_count,
    )
    t_review = time.monotonic()
    payload = _chat_json_with_retries(
        system=system,
        user_text=user,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
    )
    reviewer_model_used = str(payload.pop("_llm_model_used", f"codex:{model}"))
    logger.info("[reviewer] GPT-5.5 review DONE elapsed=%.2fs", time.monotonic() - t_review)

    feature_text_by_id = {f.feature_id: f.feature_text for f in task.claim_features}

    # 收集所有原始 evidence URL，用于回填候选 evidence 时找原数据（避免 GPT-5.5 漏字段）
    evidence_lookup: dict[str, Evidence] = {}
    launch_lookup: dict[str, tuple[str | None, str | None]] = {}
    for ao in agent_outputs:
        for c in ao.top5_candidates:
            launch_lookup[_candidate_key(c.company, c.product)] = (
                c.product_launch_date,
                c.product_launch_date_evidence_url,
            )
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
        fallback_launch_date, fallback_launch_url = _lookup_launch_date(
            launch_lookup,
            company,
            product,
        )
        product_launch_date = (
            normalize_date_string(raw.get("product_launch_date"))
            or fallback_launch_date
        )
        product_launch_date_evidence_url = (
            str(raw.get("product_launch_date_evidence_url") or "").strip()
            or fallback_launch_url
        )
        hard = scoring.evaluate_hard_rules(
            company=company,
            product=product,
            assignees=task.patent.assignees,
            evidence_urls=evidence_urls,
            feature_matches=fmt,
            patent_application_date=task.patent.application_date,
            product_launch_date=product_launch_date,
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
        product = _refine_product_scope(
            company,
            product,
            [str(a) for a in (raw.get("aliases") or [])],
        )
        aliases = _clean_aliases_for_product(
            product,
            [str(a) for a in (raw.get("aliases") or [])],
        )
        if _top5_already_has(top5, company=company, product=product, aliases=aliases):
            continue
        top5.append(_apply_product_scope_cleanup(FinalCandidate(
            rank=len(top5) + 1,
            candidate_id=str(raw.get("candidate_id", "")).strip() or f"M{len(top5)+1:03d}",
            company=company,
            product=product,
            aliases=aliases,
            product_launch_date=product_launch_date,
            product_launch_date_evidence_url=product_launch_date_evidence_url,
            score=round(score, 1),
            risk_level=risk,  # type: ignore[arg-type]
            final_feature_table=fmt,
            main_evidence_urls=evidence_urls,
            reason_for_top5=str(raw.get("reason_for_top5", "")).strip(),
            remaining_gaps=_dedupe_gaps(raw.get("remaining_gaps") or []),
        )))
        if len(top5) >= 5:
            break

    excluded = list(auto_excluded)
    soft_excluded_needs: list[NeedsManualReview] = []
    for x in (payload.get("excluded") or []):
        if not isinstance(x, dict):
            continue
        item = ReviewExcluded(
            candidate_id=str(x.get("candidate_id", "")),
            company=str(x.get("company", "")),
            product=str(x.get("product", "")),
            discard_reason=str(x.get("discard_reason", "")),
            evidence_urls=[str(u) for u in (x.get("evidence_urls") or [])],
        )
        if _is_model_hard_exclusion(item.discard_reason):
            excluded.append(item)
        else:
            soft_excluded_needs.append(NeedsManualReview(
                candidate_id=item.candidate_id,
                company=item.company,
                product=item.product,
                gap=item.discard_reason or "复核模型未给出硬性排除理由，转为待人工核查。",
                suggested_search_direction="继续补充具体型号、尺寸、能量/容量、上市日期等公开证据。",
            ))
    needs = [
        NeedsManualReview(
            candidate_id=str(x.get("candidate_id", "")),
            company=str(x.get("company", "")),
            product=_refine_product_scope(
                str(x.get("company", "")),
                str(x.get("product", "")),
                [],
            ),
            gap=str(x.get("gap", "")),
            suggested_search_direction=str(x.get("suggested_search_direction", "")),
        )
        for x in (payload.get("needs_manual_review") or []) if isinstance(x, dict)
    ] + soft_excluded_needs

    top5 = _fill_top5_from_agent_candidates(
        top5=top5,
        excluded=excluded,
        needs=needs,
        agent_outputs=agent_outputs,
        task=task,
    )
    _apply_calculated_parameter_matches(top5, agent_outputs, task)
    needs = _drop_resolved_manual_review_items(needs, top5)
    top_by_id = {c.candidate_id: c for c in top5 if c.candidate_id}
    for item in needs:
        matched = top_by_id.get(item.candidate_id)
        if matched:
            item.company = matched.company
            item.product = matched.product

    notes = str(payload.get("notes", "")).strip()
    if any(
        fm.feature_id == "F4" and fm.judgement != "证据不足"
        for c in top5
        for fm in c.final_feature_table
    ):
        notes = notes.replace(
            "所有候选在F4（表面积/能量比）上均存在显著证据缺口；",
            "部分候选的F4已可通过公开参数核算，其他候选仍存在F4证据缺口；",
        )
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
        reviewer_model=reviewer_model_used,
        elapsed_seconds=round(time.monotonic() - t0, 2),
        notes=notes,
    )


# 兼容旧导入名（有些下游代码仍可能用 review_candidate_pool）
def review_candidate_pool(_pool, task, *, reasoning_effort: str = "medium"):
    """兼容入口 — 内部已不依赖 candidate_pool；新代码请用 ``review_agent_outputs``。"""
    raise RuntimeError(
        "review_candidate_pool 已废弃。请改用 review_agent_outputs(list[AgentOutput], task)。"
    )


def _load_supplement_cache(
    path: Path | None,
    task: TaskPackage,
    source_fingerprint: str,
) -> tuple[list[AgentOutput], int] | None:
    if path is None or not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("patent_publication_no") != task.patent.publication_no:
            logger.info(
                "[reviewer] supplement CACHE SKIP reason=pub_no_mismatch path=%s",
                path,
            )
            return None
        if raw.get("agent_outputs_fingerprint") != source_fingerprint:
            logger.info(
                "[reviewer] supplement CACHE SKIP reason=agent_outputs_changed path=%s",
                path,
            )
            return None
        outputs = [
            AgentOutput.model_validate(item)
            for item in (raw.get("agent_outputs") or [])
        ]
        if not outputs:
            logger.info(
                "[reviewer] supplement CACHE SKIP reason=empty_outputs path=%s",
                path,
            )
            return None
        supplement_count = int(raw.get("supplement_count") or 0)
        logger.info(
            "[reviewer] supplement CACHE HIT path=%s agent_outputs=%d supplement_urls=%d",
            path, len(outputs), supplement_count,
        )
        return outputs, supplement_count
    except Exception as exc:  # noqa: BLE001
        logger.info("[reviewer] supplement CACHE SKIP path=%s error=%s", path, exc)
        return None


def _write_supplement_cache(
    path: Path,
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
    supplement_count: int,
    source_fingerprint: str,
) -> None:
    payload = {
        "version": 1,
        "patent_publication_no": task.patent.publication_no,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "agent_outputs_fingerprint": source_fingerprint,
        "supplement_count": supplement_count,
        "agent_outputs": [ao.model_dump() for ao in agent_outputs],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        logger.info(
            "[reviewer] supplement CACHE WRITE path=%s supplement_urls=%d",
            path, supplement_count,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("[reviewer] supplement CACHE WRITE failed path=%s error=%s", path, exc)


def _agent_outputs_fingerprint(agent_outputs: list[AgentOutput]) -> str:
    payload = [ao.model_dump(mode="json") for ao in agent_outputs]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _chat_json_with_retries(
    *,
    system: str,
    user_text: str,
    model: str,
    reasoning_effort: str,
    verbosity: str,
) -> dict[str, Any]:
    logger.info("[reviewer] GPT-5.5 review START_WITH_FALLBACK model=%s attempts=3", model)
    return controller.chat_json(
        system=system,
        user_text=user_text,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
        fallback_label="reviewer",
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
    *,
    search_session: SearchSession,
) -> tuple[list[AgentOutput], int]:
    """最终复核前对证据不足项执行代码侧补搜。"""
    outputs = [ao.model_copy(deep=True) for ao in agent_outputs]
    seen_queries = {
        evidence_strategy.normalize_query(q.query)
        for ao in outputs
        for q in ao.queries_used
        if q.query
    }
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
            added += _supplement_candidate(cand, task, seen_queries, search_session)
    return outputs, added


def _supplement_candidate(
    cand: Candidate,
    task: TaskPackage,
    seen_queries: set[str],
    search_session: SearchSession,
) -> int:
    existing_urls = {
        evidence_strategy.canonicalize_url(ev.url)
        for fm in cand.feature_match_table
        for ev in fm.evidence
        if ev.url
    } | {evidence_strategy.canonicalize_url(url) for url in cand.main_evidence_urls}
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
    target_match_by_id = {fm.feature_id: fm for fm in target_features}
    claim_targets = [
        feature_by_id[fm.feature_id]
        for fm in target_features
        if fm.feature_id in feature_by_id
    ]
    evidence_targets = evidence_strategy.build_evidence_targets(
        cand.company,
        cand.product,
        claim_targets,
        aliases=cand.aliases,
        industry_tag=task.industry_tag,
        include_counter=False,
    )
    for target in evidence_targets[:REVIEW_SUPPLEMENT_TARGETS_PER_CANDIDATE]:
        target_feature_ids = tuple(
            fid for fid in target.feature_ids
            if fid in target_match_by_id
        )
        if not target_feature_ids:
            continue
        logger.info(
            "[reviewer] supplement START candidate=%s/%s target=%s features=%s",
            cand.company,
            cand.product,
            target.label,
            ",".join(target_feature_ids),
        )
        target_existing_urls = {
            evidence_strategy.canonicalize_url(ev.url)
            for fid in target_feature_ids
            for ev in target_match_by_id[fid].evidence
            if ev.url
        }
        target_added = 0
        for query in target.queries[:REVIEW_SUPPLEMENT_QUERIES_PER_TARGET]:
            if target_added >= REVIEW_SUPPLEMENT_HITS_PER_FEATURE:
                break
            qkey = evidence_strategy.normalize_query(query)
            if qkey in seen_queries:
                logger.info(
                    "[reviewer] supplement SKIP duplicate_query target=%s query=%r",
                    target.target_id,
                    query,
                )
                continue
            seen_queries.add(qkey)
            logger.info(
                "[reviewer] supplement query target=%s features=%s query=%r",
                target.target_id,
                ",".join(target_feature_ids),
                query,
            )
            try:
                hits = search_session.search(
                    query,
                    engines=_review_engines_for_target(target),
                    num_per_engine=REVIEW_SUPPLEMENT_HITS_PER_FEATURE,
                    log_context="[reviewer]",
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("review supplement search failed %r: %s", query, exc)
                continue
            hits = sorted(
                hits,
                key=lambda h: evidence_strategy.tier_rank(
                    h.url,
                    h.title,
                    industry_tag=task.industry_tag,
                ) + _parameter_hit_bonus(h, target),
                reverse=True,
            )
            for hit in hits:
                if target_added >= REVIEW_SUPPLEMENT_HITS_PER_FEATURE:
                    break
                hit_url = evidence_strategy.canonicalize_url(hit.url)
                if not hit_url or hit_url in target_existing_urls:
                    if hit.url:
                        logger.info("[reviewer] supplement SKIP duplicate_feature_url url=%s", hit_url)
                    continue
                if not evidence_strategy.is_relevant_hit(
                    hit_url,
                    hit.title,
                    hit.snippet,
                    cand.company,
                    cand.product,
                    cand.aliases,
                    industry_tag=task.industry_tag,
                ):
                    logger.info(
                        "[reviewer] supplement SKIP low_relevance title=%r url=%s",
                        (hit.title or "")[:120],
                        hit_url,
                    )
                    continue
                hit.url = hit_url
                evidence = _evidence_from_hit(
                    hit,
                    target_feature_ids,
                    search_session,
                    industry_tag=task.industry_tag,
                )
                for fid in target_feature_ids:
                    target_match_by_id[fid].evidence.append(evidence)
                target_existing_urls.add(hit_url)
                if hit_url not in existing_urls:
                    cand.main_evidence_urls.append(hit_url)
                existing_urls.add(hit_url)
                added += 1
                target_added += 1
                logger.info(
                    "[reviewer] supplement ADD features=%s tier=%s source=%s url=%s",
                    ",".join(target_feature_ids),
                    evidence_strategy.tier_label(
                        hit.url,
                        hit.title,
                        industry_tag=task.industry_tag,
                    ),
                    evidence.source_type,
                    hit.url,
                )
    if added:
        cand.main_evidence_urls = sorted(set(cand.main_evidence_urls))
    return added


def _parameter_hit_bonus(hit: Any, target: evidence_strategy.EvidenceTarget) -> int:
    if target.target_id != "spec":
        return 0
    text = f"{getattr(hit, 'url', '')} {getattr(hit, 'title', '')} {getattr(hit, 'snippet', '')}".lower()
    bonus = 0
    if any(x in text for x in ("dimension", "dimensions", "尺寸", "长", "宽", "厚")):
        bonus += 4
    if re.search(r"\d{2,4}(?:\.\d+)?\s*(?:x|×|\\|\*)\s*\d{1,4}", text):
        bonus += 3
    if re.search(r"\d{2,5}(?:\.\d+)?\s*wh(?!\s*/\s*kg)", text, flags=re.I):
        bonus += 4
    if re.search(r"\d(?:\.\d+)?\s*v\b", text, flags=re.I):
        bonus += 2
    if re.search(r"\d{2,4}(?:\.\d+)?\s*ah\b", text, flags=re.I):
        bonus += 2
    if any(x in text for x in ("datasheet", "specification", "规格书", "产品标准", "product standard")):
        bonus += 2
    return bonus


def _evidence_from_hit(
    hit,
    feature_ids: tuple[str, ...],
    search_session: SearchSession,
    *,
    industry_tag: str | None = None,
) -> Evidence:
    text = hit.snippet or ""
    title = hit.title or ""
    if evidence_strategy.should_read_url(hit.url, title, industry_tag=industry_tag):
        try:
            page = search_session.read_url(hit.url, log_context="[reviewer]")
            text = page.text or text
            title = page.title or title
        except Exception as exc:  # noqa: BLE001
            logger.info("review supplement read failed %s: %s", hit.url[:80], exc)
    else:
        logger.info(
            "review supplement read skipped unreadable_or_patent tier=%s url=%s",
            evidence_strategy.tier_label(hit.url, title, industry_tag=industry_tag),
            hit.url[:120],
        )
    return Evidence(
        url=hit.url,
        title=title,
        source_type=evidence_strategy.source_type_from_url_title(
            hit.url,
            title,
            industry_tag=industry_tag,
        ),
        source_reliability=evidence_strategy.reliability_from_url_title(
            hit.url,
            title,
            industry_tag=industry_tag,
        ),
        summary=(
            f"[最终复核补搜 / {evidence_strategy.tier_label(hit.url, title, industry_tag=industry_tag)}] "
            + text[:REVIEW_SUPPLEMENT_SUMMARY_CHARS]
        ).strip(),
        supported_features=list(feature_ids),
    )
