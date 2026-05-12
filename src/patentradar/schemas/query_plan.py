"""Module-two query generation schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SearchProviderName = Literal["tavily", "bocha", "exa", "brave"]
QueryLanguage = Literal["zh", "en", "mixed"]
QueryIntent = Literal[
    "claim_feature",
    "market_name",
    "specification",
    "industry_company",
    "launch_date",
    "evidence",
]


class SearchQuery(BaseModel):
    query_id: str = Field(..., pattern=r"^Q\d{2}$")
    query: str = Field(..., min_length=2)
    intent: QueryIntent
    language: QueryLanguage
    target_feature_ids: list[str] = Field(default_factory=list)
    preferred_providers: list[SearchProviderName] = Field(default_factory=list)

    @field_validator("preferred_providers")
    @classmethod
    def validate_provider_count(cls, value: list[SearchProviderName]) -> list[SearchProviderName]:
        return list(dict.fromkeys(value))


class ApplicantSelfSignals(BaseModel):
    """LLM-derived hints for filtering out the patent applicant's own
    products/sites from search results. Generated per task in step 1 because
    the applicant changes with every input patent. `aliases` may contain
    mixed-language entries — for a CN patent the LLM emits mostly Chinese plus
    common English brand abbreviations; for a US patent it emits mostly
    English plus localized variants. The post-filter does case-insensitive
    substring match, so the field is language-agnostic."""

    domains: list[str] = Field(default_factory=list, description="self-owned domains, lowercase")
    aliases: list[str] = Field(default_factory=list)


class QueryPlan(BaseModel):
    publication_no: str
    claim_1_summary: str
    applicant_self_signals: ApplicantSelfSignals = Field(default_factory=ApplicantSelfSignals)
    queries: list[SearchQuery]

    @model_validator(mode="after")
    def validate_query_count(self) -> "QueryPlan":
        if not 30 <= len(self.queries) <= 50:
            raise ValueError("queries must contain 30-50 items")
        return self
