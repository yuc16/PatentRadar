"""Competitor candidate schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class Candidate(BaseModel):
    candidate_id: str = Field(..., pattern=r"^P\d{2}$")
    company: str = Field(..., min_length=1)
    company_en: str = ""
    product_name: str = Field(..., min_length=1)
    product_name_en: str = ""
    product_version: str = ""
    market: str = Field(..., min_length=1)
    reason_for_deep_dive: str = Field(..., min_length=1)
    source_result_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    initial_evidence_summary: str = ""

    @field_validator("source_urls")
    @classmethod
    def dedupe_urls(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(url for url in value if url))

    @model_validator(mode="after")
    def validate_product_granularity(self) -> "Candidate":
        if self.product_name.strip() == self.company.strip() and not self.product_version.strip():
            raise ValueError("candidate must be a concrete product, not only a company")
        return self


class CandidateShortlist(BaseModel):
    publication_no: str
    candidates: list[Candidate]

    @model_validator(mode="after")
    def validate_candidate_count(self) -> "CandidateShortlist":
        if not self.candidates:
            raise ValueError("candidates must not be empty")
        # Dedupe key includes product_version so the same product line at
        # different specs (e.g. L500 325Ah / 350Ah / 730Ah) is preserved as
        # distinct candidates per spec requirement「竞品要细到具体版本」.
        product_keys = {
            (
                candidate.company.strip().lower(),
                candidate.product_name.strip().lower(),
                candidate.product_version.strip().lower(),
            )
            for candidate in self.candidates
        }
        if len(product_keys) != len(self.candidates):
            raise ValueError("candidates must be mutually exclusive on (company, product_name, product_version)")
        return self
