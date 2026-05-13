"""Evidence and claim-1 comparison schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .candidate import Candidate
from .query_plan import SearchProviderName


FeatureMatchStatus = Literal["明确满足", "可能满足", "证据不足", "明确不满足"]


class EvidenceSource(BaseModel):
    url: str
    title: str = ""
    source_name: str = ""
    snippet: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must be absolute")
        return value


class FeatureComparison(BaseModel):
    # Module two only ever emits C1-F* (claim 1). Module three extends to all
    # claims, so the pattern is relaxed to any C{n}-F{m}. Strict per-module
    # bounds are still enforced by the json-schema passed to the LLM API.
    feature_id: str = Field(..., pattern=r"^C\d+-F\d+$")
    patent_feature: str
    competitor_feature: str = ""
    status: FeatureMatchStatus
    score: float = Field(ge=0, le=1)
    evidence: list[EvidenceSource] = Field(default_factory=list)
    reasoning: str
    # Filled by module three's round-1 LLM: queries the model wants the code
    # side to run before round 2 finalizes the comparison. Default empty so
    # module two's existing output stays schema-compatible.
    suggested_followup_queries: list[str] = Field(default_factory=list, max_length=5)
    # 模块三 round 2 终判时，对权 1 中 status ∈ {可能满足, 证据不足} 的特征
    # 必填：写清"还缺什么 + 去哪找 + 下一步搜索建议（具体 query 字串）"。
    # 模块四 report 直接复用这个字段写"证据缺口与下一步搜索建议"段落，避免
    # 让 LLM 在生成报告时再临场造 query。默认空字符串。
    evidence_gap_brief: str = ""

    @model_validator(mode="after")
    def validate_score(self) -> "FeatureComparison":
        expected = {
            "明确满足": 1.0,
            "可能满足": 0.8,
            "证据不足": 0.3,
            "明确不满足": 0.0,
        }[self.status]
        self.score = expected
        seen_urls: set[str] = set()
        deduped: list[EvidenceSource] = []
        for evidence in self.evidence:
            if evidence.url in seen_urls:
                continue
            seen_urls.add(evidence.url)
            deduped.append(evidence)
        self.evidence = deduped
        return self


class CandidateEvidence(BaseModel):
    candidate: Candidate
    launch_date: str = ""
    launch_date_evidence: list[EvidenceSource] = Field(default_factory=list)
    disqualified: bool = False
    disqualification_reason: str = ""
    comparisons: list[FeatureComparison]
    # total_score is a 0-100 percentage. Per-feature `score` (1.0/0.8/0.3/0.0)
    # is the satisfaction ratio for that feature; total = mean(ratios) × 100.
    # All features are weighted equally (each feature contributes 100/N points
    # at full satisfaction).
    total_score: float = Field(ge=0, le=100)
    searched_queries: list[str] = Field(default_factory=list)
    searched_providers: list[SearchProviderName] = Field(default_factory=list)

    @model_validator(mode="after")
    def derive_score(self) -> "CandidateEvidence":
        if any(item.status == "明确不满足" for item in self.comparisons):
            self.disqualified = True
            if not self.disqualification_reason:
                self.disqualification_reason = "存在公开证据证明至少一个权1技术特征明确不满足"
        if self.disqualified:
            self.total_score = 0.0
        elif self.comparisons:
            average_ratio = sum(item.score for item in self.comparisons) / len(self.comparisons)
            self.total_score = round(average_ratio * 100, 2)
        else:
            self.total_score = 0.0
        return self


class EvidenceBatchResult(BaseModel):
    publication_no: str
    batch_id: str
    results: list[CandidateEvidence]


class TopCompetitorReport(BaseModel):
    publication_no: str
    top_competitors: list[CandidateEvidence]
    excluded_candidates: list[CandidateEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_top_count(self) -> "TopCompetitorReport":
        if len(self.top_competitors) > 30:
            raise ValueError("top_competitors is unexpectedly large")
        return self
