"""Patent metadata schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PatentInfo(BaseModel):
    publication_no: str
    title: str = ""
    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    application_date: str = ""
    google_patents_url: str
    pdf_url: str = ""
    fetched_at: str
