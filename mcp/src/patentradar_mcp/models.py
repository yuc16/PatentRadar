from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ProviderName = Literal["tavily", "bocha", "exa", "brave"]
PROVIDERS: tuple[ProviderName, ...] = ("tavily", "bocha", "exa", "brave")
SearchMode = Literal["discovery", "evidence"]
QueryLanguage = Literal["zh", "en", "mixed"]
QUERY_LANGUAGES = {"zh", "en", "mixed"}
QueryIntent = Literal[
    "claim_feature",
    "market_name",
    "specification",
    "industry_company",
    "launch_date",
    "evidence",
]
QUERY_INTENTS = {
    "claim_feature",
    "market_name",
    "specification",
    "industry_company",
    "launch_date",
    "evidence",
}


class StartAnalysisInput(BaseModel):
    publication_no: str

    @field_validator("publication_no")
    @classmethod
    def normalize_publication_no(cls, value: str) -> str:
        normalized = re.sub(r"[\s-]", "", value).upper()
        if not re.fullmatch(r"[A-Z]{2}\d{6,}[A-Z]?\d?", normalized):
            raise ValueError("请输入 CN/US/EP/JP 等规范专利公开号")
        return normalized


class WorkSubmission(BaseModel):
    case_id: str
    stage: str
    artifact: dict[str, Any]


class ProviderQuery(BaseModel):
    query_id: str = Field(pattern=r"^Q\d{2,3}$")
    query: str = Field(min_length=2, max_length=500)
    intent: QueryIntent = "evidence"
    language: QueryLanguage = "mixed"
    target_feature_ids: list[str] = Field(default_factory=list)
    preferred_providers: list[ProviderName] = Field(default_factory=list)

    @field_validator("preferred_providers")
    @classmethod
    def dedupe_providers(cls, value: list[ProviderName]) -> list[ProviderName]:
        return list(dict.fromkeys(value))


class ProviderSearchInput(BaseModel):
    case_id: str
    queries: list[ProviderQuery] = Field(min_length=1, max_length=200)
    search_mode: SearchMode = "discovery"
    max_results_per_provider: int = Field(default=5, ge=1, le=10)
    max_providers_per_query: int = Field(default=3, ge=1, le=3)
    target_max_results: int = Field(default=400, ge=1, le=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_queries(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not isinstance(value.get("queries"), list):
            return value
        copied_input = dict(value)
        normalized: list[Any] = []
        seen_queries: set[str] = set()
        for item in value["queries"]:
            if isinstance(item, str):
                query = item.strip()[:500]
                query_data: dict[str, Any] = {}
            elif isinstance(item, dict):
                query_data = dict(item)
                query = str(query_data.get("query") or "").strip()[:500]
            else:
                normalized.append(item)
                continue
            if len(query) < 2:
                continue
            query_key = query.casefold()
            if query_key in seen_queries:
                continue
            seen_queries.add(query_key)
            query_data["query_id"] = f"Q{len(normalized) + 1:03d}"
            query_data["query"] = query
            if query_data.get("intent") not in QUERY_INTENTS:
                query_data["intent"] = "evidence"
            if query_data.get("language") not in QUERY_LANGUAGES:
                query_data["language"] = "zh" if re.search(r"[\u3400-\u9fff]", query) else "en"
            normalized.append(query_data)
        copied_input["queries"] = normalized
        return copied_input

    @model_validator(mode="after")
    def validate_queries(self) -> "ProviderSearchInput":
        query_ids = [item.query_id for item in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("query_id 不能重复")
        query_texts = [item.query for item in self.queries]
        if len(query_texts) != len(set(query_texts)):
            raise ValueError("query 不能重复")
        return self


class KeyUpdate(BaseModel):
    tavily: str | None = None
    bocha: str | None = None
    exa: str | None = None
    brave: str | None = None

    def supplied(self) -> dict[ProviderName, str]:
        values: dict[ProviderName, str] = {}
        for provider in PROVIDERS:
            value = getattr(self, provider)
            if value is not None and value.strip():
                values[provider] = value.strip()
        return values
