"""Patent metadata schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from patentradar.core.constants import PATENT_COUNTRY_CODES


class PatentInfo(BaseModel):
    publication_no: str
    country_code: str = ""
    title: str = ""
    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    application_date: str = ""
    google_patents_url: str
    pdf_url: str = ""
    fetched_at: str

    @model_validator(mode="after")
    def _derive_country_code(self) -> "PatentInfo":
        if not self.country_code and self.publication_no:
            prefix = self.publication_no[:2].upper()
            if prefix in PATENT_COUNTRY_CODES:
                self.country_code = prefix
        return self
