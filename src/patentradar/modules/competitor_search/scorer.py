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
    seen_companies: set[str] = set()
    deduped: list[CandidateEvidence] = []
    for item in valid:
        company_key = item.candidate.company.strip().lower()
        if company_key in seen_companies:
            continue
        seen_companies.add(company_key)
        deduped.append(item)
    if len(deduped) <= top_n:
        selected = deduped
    else:
        cutoff = deduped[top_n - 1].total_score
        selected = [candidate for candidate in deduped if candidate.total_score >= cutoff]
    return TopCompetitorReport(
        publication_no=publication_no,
        top_competitors=selected,
        excluded_candidates=excluded,
    )
