"""Claim-related schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClaimFeature(BaseModel):
    feature_id: str = Field(
        ...,
        pattern=r"^C\d+-F\d+$",
        description="Feature id within the claim, such as C1-F1.",
    )
    feature_text: str = Field(..., description="A faithful contiguous claim text fragment.")


class Claim(BaseModel):
    claim_no: int
    claim_text: str
    features: list[ClaimFeature] = Field(default_factory=list)
