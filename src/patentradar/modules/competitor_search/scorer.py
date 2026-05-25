"""Step 5 scoring and ranking."""

from __future__ import annotations

from patentradar.schemas import CandidateEvidence, TopCompetitorReport


def rank_top_competitors(
    *,
    publication_no: str,
    candidates: list[CandidateEvidence],
    top_n: int = 5,
) -> TopCompetitorReport:
    valid = [candidate for candidate in candidates if not candidate.disqualified]
    excluded = [candidate for candidate in candidates if candidate.disqualified]
    valid.sort(
        key=lambda item: (
            item.total_score,
            sum(len(comparison.evidence) for comparison in item.comparisons),
            item.candidate.candidate_id,
        ),
        reverse=True,
    )
    # 同公司只保留最高分产品：上面已按 (score 降序, evidence 数, id) 排过，
    # 第一次遇到的 company 就是该公司分数最高的产品；后续同 company 的丢弃。
    # 空 company（LLM 偶尔漏写）不参与 dedup：否则一堆"未知公司"会互相挤掉
    # 只留排序最早那条，相当于硬丢若干合法候选。
    seen_companies: set[str] = set()
    deduped: list[CandidateEvidence] = []
    for item in valid:
        company_key = item.candidate.company.strip().lower()
        if company_key:
            if company_key in seen_companies:
                continue
            seen_companies.add(company_key)
        deduped.append(item)
    # 硬限 top_n：之前用 cutoff `>=` 会让 tied 同分候选全部纳入，模块 3 每多
    # 一个候选就是 2 次 LLM + N 次搜索，开销不可控。tiebreaker 已由 sort key
    # （evidence 数 → candidate_id）稳定决定。
    selected = deduped[:top_n]
    return TopCompetitorReport(
        publication_no=publication_no,
        top_competitors=selected,
        excluded_candidates=excluded,
    )
