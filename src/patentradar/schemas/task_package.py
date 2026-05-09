"""Module-one output schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from patentradar.core.constants import TECHNOLOGY_TAGS

from .claims import Claim, ClaimFeature
from .patent import PatentInfo

DecomposeSource = Literal["html", "pdf_vision"]


class TaskPackage(BaseModel):
    patent: PatentInfo
    technology_tag: str
    claims: list[Claim]
    claim_1_text: str
    claim_1_features: list[ClaimFeature] = Field(default_factory=list)
    claims_source: DecomposeSource
    model: str
    reasoning_effort: str

    @field_validator("technology_tag")
    @classmethod
    def validate_technology_tag(cls, value: str) -> str:
        if value not in TECHNOLOGY_TAGS:
            raise ValueError(f"technology_tag must be one of {TECHNOLOGY_TAGS}")
        return value

    @field_validator("claims")
    @classmethod
    def validate_claims(cls, value: list[Claim]) -> list[Claim]:
        if not value:
            raise ValueError("claims must not be empty")
        if value[0].claim_no != 1:
            raise ValueError("claims must start from claim 1")
        return value
