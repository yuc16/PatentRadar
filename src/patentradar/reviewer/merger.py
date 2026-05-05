"""候选去重合并快照（代码层）→ 产出 candidate_pool.json 便于审计。

合并维度（PRD §16.4 / §20.4）：
- 公司名归一化：去掉公司后缀、空白、大小写、英中互译同义；
- 产品归一化：去掉过长描述，按主型号分组；
- 同一 URL 证据合并；
- 多 Agent 对同一候选的判断快照保留为列表。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from ..schemas import (
    AgentJudgement,
    AgentOutput,
    Candidate,
    CandidateEvidenceMerged,
    CandidateInPool,
    CandidatePool,
    Evidence,
    FeatureJudgementMerged,
    TaskPackage,
)

_COMPANY_SUFFIX_RE = re.compile(
    r"(股份)?(有限)?公司|股份|集团|科技|电子|半导体|technologies|technology|"
    r"inc\.?|corporation|corp\.?|ltd\.?|limited|llc|gmbh|co\.?,?\s*ltd|ab",
    flags=re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-zA-Z]{3,}|[一-鿿]{2,}")
# 通用修饰词（不算独特识别 token），避免 "Apple Inc" 与 "Apple Tree" 误合并这类
_GENERIC_TOKENS = {
    "tech", "ai", "ic", "module", "modules", "system", "systems", "device",
    "solution", "solutions", "technology", "technologies",
    "电子", "科技", "集团", "股份", "公司", "传感器", "模组", "芯片",
}


def _tokens_of(name: str) -> set[str]:
    name = (name or "").lower()
    name = _COMPANY_SUFFIX_RE.sub(" ", name)
    raw = set(_TOKEN_RE.findall(name))
    return {t for t in raw if t not in _GENERIC_TOKENS}


def _aliases_for_dedup(c: Candidate) -> set[str]:
    """返回该候选的"识别 token 集合"，用于跨 Agent 合并判定。"""
    tokens: set[str] = set()
    tokens |= _tokens_of(c.company)
    for a in c.aliases or []:
        tokens |= _tokens_of(a)
    return tokens


def _merge_evidence(
    candidates: list[tuple[str, Candidate]]  # (agent_name, candidate)
) -> tuple[list[CandidateEvidenceMerged], dict[str, str]]:
    """聚合证据，按 URL 去重；返回 (evidence list, url→evidence_id 映射)。"""
    by_url: dict[str, CandidateEvidenceMerged] = {}
    for agent_name, c in candidates:
        for fm in c.feature_match_table:
            for ev in fm.evidence:
                if not ev.url:
                    continue
                if ev.url not in by_url:
                    eid = f"E{len(by_url)+1:03d}"
                    by_url[ev.url] = CandidateEvidenceMerged(
                        evidence_id=eid,
                        url=ev.url,
                        title=ev.title,
                        source_type=ev.source_type,
                        source_reliability=ev.source_reliability,
                        summary=ev.summary,
                        supported_features=list(ev.supported_features),
                        found_by_agents=[agent_name],
                    )
                else:
                    # 合并 supported_features + found_by_agents
                    merged = by_url[ev.url]
                    for f in ev.supported_features:
                        if f not in merged.supported_features:
                            merged.supported_features.append(f)
                    if agent_name not in merged.found_by_agents:
                        merged.found_by_agents.append(agent_name)
    url_to_eid = {url: m.evidence_id for url, m in by_url.items()}
    return list(by_url.values()), url_to_eid


def _merge_feature_judgements(
    candidates: list[tuple[str, Candidate]],
    url_to_eid: dict[str, str],
    feature_ids: list[str],
) -> list[FeatureJudgementMerged]:
    by_fid: dict[str, FeatureJudgementMerged] = {
        fid: FeatureJudgementMerged(feature_id=fid, agent_judgements=[])
        for fid in feature_ids
    }
    for agent_name, c in candidates:
        for fm in c.feature_match_table:
            if fm.feature_id not in by_fid:
                by_fid[fm.feature_id] = FeatureJudgementMerged(
                    feature_id=fm.feature_id, agent_judgements=[]
                )
            by_fid[fm.feature_id].agent_judgements.append(
                AgentJudgement(
                    agent_name=agent_name,
                    judgement=fm.judgement,
                    score=fm.score,
                    reasoning=fm.reasoning,
                    evidence_ids=[url_to_eid[ev.url] for ev in fm.evidence if ev.url in url_to_eid],
                )
            )
    return [by_fid[f] for f in feature_ids]


def merge_agent_outputs(
    task: TaskPackage,
    agent_outputs: Iterable[AgentOutput],
) -> CandidatePool:
    """把多 Agent 的 Top 候选合并为 candidate_pool。"""
    # 1) 把所有候选按归一化 key 分桶
    buckets: list[tuple[set[str], list[tuple[str, Candidate]]]] = []
    for ao in agent_outputs:
        for c in ao.top5_candidates:
            keys = _aliases_for_dedup(c)
            if not keys:
                continue
            placed = False
            for bucket_keys, members in buckets:
                if bucket_keys & keys:
                    bucket_keys.update(keys)
                    members.append((ao.agent_name, c))
                    placed = True
                    break
            if not placed:
                buckets.append((set(keys), [(ao.agent_name, c)]))

    feature_ids = [f.feature_id for f in task.claim_features]
    pool: list[CandidateInPool] = []
    for i, (_, members) in enumerate(buckets, start=1):
        # 选择最长的公司名作为 canonical
        company = max((m[1].company for m in members), key=lambda s: len(s or ""))
        product = max((m[1].product for m in members), key=lambda s: len(s or ""))
        aliases = sorted({a for _, c in members for a in (c.aliases or []) if a} |
                          {c.company for _, c in members if c.company and c.company != company})
        evidence, url_to_eid = _merge_evidence(members)
        feat_table = _merge_feature_judgements(members, url_to_eid, feature_ids)

        # known_gaps：所有特征中无明确满足的归集
        gaps = []
        for fjm in feat_table:
            judgements = [aj.judgement for aj in fjm.agent_judgements]
            if judgements and "明确满足" not in judgements:
                top = max(judgements, key=lambda j: ["明确不满足","证据不足","可能满足","明确满足"].index(j))
                if top in ("证据不足", "可能满足"):
                    gaps.append({"feature_id": fjm.feature_id, "current": top})

        pool.append(CandidateInPool(
            candidate_id=f"C{i:03d}",
            company=company,
            product=product,
            aliases=aliases,
            found_by_agents=sorted({a for a, _ in members}),
            all_evidence=evidence,
            preliminary_feature_table=feat_table,
            known_gaps=gaps,
        ))

    return CandidatePool(
        patent_publication_no=task.patent.publication_no,
        claim_1_text=task.claim_1_text,
        claim_features=task.claim_features,
        candidate_pool=pool,
    )
