"""Module four report schemas.

The final report itself is markdown text, not a strict schema. When the
infringement-risk threshold (max_total_score >= 80) is crossed, we attach a
deep link into Google Patents Advanced Search so the human reviewer can
inspect same-applicant + same-title patents (often INPADOC family siblings).
That hint payload is persisted as `similar_patents.json` for traceability.
"""

from __future__ import annotations

from pydantic import BaseModel


class SimilarPatentSearchHint(BaseModel):
    """Persisted to similar_patents.json. Just a deep link — no scraping."""

    source_publication_no: str
    triggered_by_total_score: float
    threshold: float = 80.0
    country_code: str
    applicant: str
    title: str
    google_patents_search_url: str
