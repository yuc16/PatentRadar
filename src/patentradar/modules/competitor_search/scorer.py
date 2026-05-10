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
    if len(valid) <= top_n:
        selected = valid
    else:
        cutoff = valid[top_n - 1].total_score
        selected = [candidate for candidate in valid if candidate.total_score >= cutoff]
    return TopCompetitorReport(
        publication_no=publication_no,
        top_competitors=selected,
        excluded_candidates=excluded,
    )
