"""Normalized search result schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .query_plan import SearchProviderName


class SearchResult(BaseModel):
    result_id: str
    query_id: str
    query: str
    provider: SearchProviderName
    title: str
    url: str
    snippet: str = ""
    published_date: str = ""
    rank: int = Field(ge=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must be absolute")
        return value


class SearchResultsArtifact(BaseModel):
    publication_no: str
    results: list[SearchResult]
