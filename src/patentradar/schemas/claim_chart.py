"""Module three full claim-chart schemas.

A FullClaimChartCandidate carries the complete claim-by-claim comparison for
one TOP5 competitor (i.e., all claims, not only claim 1 like module two).

Scoring philosophy: **total_score is computed from claim 1 alone**.
Non-claim-1 comparisons are present for report completeness only — they
do not influence ranking. This matches the user's intent: module three
扩展非权1对比是为了完整性，最终评分仍然只看权1.

Use the same FeatureComparison schema as module two so evidence URLs and
status taxonomy stay consistent across the report.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from .candidate import Candidate
from .evidence import EvidenceSource, FeatureComparison
from .query_plan import SearchProviderName


class ClaimChartEntry(BaseModel):
    """One claim's worth of FeatureComparison entries plus aggregate score."""

    claim_no: int = Field(..., ge=1)
    claim_text: str
    comparisons: list[FeatureComparison]
    claim_score: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def derive_claim_score(self) -> "ClaimChartEntry":
        if not self.comparisons:
            self.claim_score = 0.0
            return self
        # If any comparison is 明确不满足, the claim as a whole fails;
        # claim_score stays at 0 to signal failure for this claim.
        if any(c.status == "明确不满足" for c in self.comparisons):
            self.claim_score = 0.0
            return self
        average = sum(c.score for c in self.comparisons) / len(self.comparisons)
        self.claim_score = round(average * 100, 2)
        return self


class FullClaimChartCandidate(BaseModel):
    """Complete claim chart for one TOP5 competitor."""

    candidate: Candidate
    # Carried over from module two — module three trusts these and doesn't requery.
    launch_date: str = ""
    launch_date_evidence: list[EvidenceSource] = Field(default_factory=list)
    disqualified: bool = False
    disqualification_reason: str = ""
    # Per-claim breakdown.
    claim_charts: list[ClaimChartEntry]
    # Score aggregations.
    claim_1_score: float = Field(ge=0, le=100)
    total_score: float = Field(ge=0, le=100)
    # Provenance.
    searched_queries: list[str] = Field(default_factory=list)
    searched_providers: list[SearchProviderName] = Field(default_factory=list)

    @field_validator("claim_charts")
    @classmethod
    def validate_claim_order(cls, value: list[ClaimChartEntry]) -> list[ClaimChartEntry]:
        if not value:
            raise ValueError("claim_charts must not be empty")
        if value[0].claim_no != 1:
            raise ValueError("claim_charts must start with claim 1")
        nos = [entry.claim_no for entry in value]
        if nos != sorted(nos):
            raise ValueError("claim_charts must be sorted by claim_no")
        return value

    @model_validator(mode="after")
    def derive_total_score(self) -> "FullClaimChartCandidate":
        # Disqualification rule: ONLY claim 1's 明确不满足 triggers disqualified.
        # Dependent claims are narrower than claim 1 (they add limitations on
        # top of claim 1). A competitor that fails a dependent limitation is
        # still potentially infringing claim 1 — so we must NOT disqualify
        # them. Each dependent claim's claim_score will naturally drop to 0
        # via ClaimChartEntry.derive_claim_score; that's reflected in the
        # per-claim report but does not affect total_score.
        claim_1_entry = next((e for e in self.claim_charts if e.claim_no == 1), None)
        if claim_1_entry is not None:
            if any(c.status == "明确不满足" for c in claim_1_entry.comparisons):
                self.disqualified = True
                if not self.disqualification_reason:
                    self.disqualification_reason = (
                        "公开证据证明竞品在权利要求 1 的至少一个技术特征上明确不满足"
                    )
        if self.disqualified:
            self.claim_1_score = 0.0
            self.total_score = 0.0
            return self
        # total_score = claim 1's claim_score. Dependent claim_scores are kept
        # per-entry for the final report but do not enter the ranking score.
        if claim_1_entry is not None:
            self.claim_1_score = claim_1_entry.claim_score
            self.total_score = claim_1_entry.claim_score
        else:
            self.claim_1_score = 0.0
            self.total_score = 0.0
        return self


class FullClaimChartReport(BaseModel):
    """Final module-three output: complete claim charts for the TOP5."""

    publication_no: str
    top_competitors: list[FullClaimChartCandidate]
    excluded_candidates: list[FullClaimChartCandidate] = Field(default_factory=list)
