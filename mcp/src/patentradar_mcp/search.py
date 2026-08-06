from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urldefrag

import httpx

from .models import PROVIDERS, ProviderName, ProviderQuery, SearchMode


_BRAVE_SEARCH_LANG = {
    "CN": "zh-hans",
    "TW": "zh-hans",
    "HK": "zh-hans",
    "US": "en",
    "GB": "en",
    "CA": "en",
    "AU": "en",
    "IN": "en",
    "JP": "jp",
    "KR": "ko",
    "DE": "de",
    "FR": "fr",
    "RU": "ru",
}
_BRAVE_SKIP_COUNTRY = {"EP", "WO"}
_EVIDENCE_PROVIDER_ORDER: list[ProviderName] = ["bocha", "brave", "tavily", "exa"]


class ProviderSearchService:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30.0) -> None:
        self.transport = transport
        self.timeout = timeout

    async def search(
        self,
        *,
        queries: list[ProviderQuery],
        keys: dict[ProviderName, str],
        max_results: int,
        search_mode: SearchMode = "discovery",
        max_providers_per_query: int = 3,
        target_max_results: int = 400,
        country_code: str = "",
    ) -> dict[str, Any]:
        query_texts = [item.query for item in queries]
        query_plan = [item.model_dump(mode="json") for item in queries]
        if not keys:
            return {
                "queries": query_texts,
                "query_plan": query_plan,
                "search_modes": [search_mode],
                "configured_providers": [],
                "attempted_providers": [],
                "successful_providers": [],
                "quota_limited_providers": [],
                "routing": [],
                "result_count": 0,
                "results": [],
                "errors": [],
                "usable": False,
                "fallback_reason": "no_provider_keys",
            }
        semaphore = asyncio.Semaphore(8)
        routed_queries = [
            (query, self._providers_for_query(query, keys, search_mode, max_providers_per_query))
            for query in queries
        ]
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            tasks = [
                self._one(client, semaphore, provider, key, query, max_results, country_code)
                for query, providers in routed_queries
                for provider in providers
                for key in [keys[provider]]
            ]
            batches = await asyncio.gather(*tasks)

        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        successful_providers: list[ProviderName] = []
        for batch_results, error in batches:
            if error:
                errors.append(error)
            if batch_results:
                provider = batch_results[0]["provider"]
                if provider not in successful_providers:
                    successful_providers.append(provider)
            for result in batch_results:
                if len(results) >= target_max_results:
                    break
                canonical = _canonical_url(result["url"])
                if not canonical or canonical in seen_urls:
                    continue
                seen_urls.add(canonical)
                result["url"] = canonical
                result["result_id"] = f"R{len(results) + 1:04d}"
                results.append(result)
        attempted_providers = list(
            dict.fromkeys(provider for _, providers in routed_queries for provider in providers)
        )
        quota_limited_providers = list(
            dict.fromkeys(
                error["provider"]
                for error in errors
                if error.get("category") == "quota_or_auth"
            )
        )
        return {
            "queries": query_texts,
            "query_plan": query_plan,
            "search_modes": [search_mode],
            "configured_providers": [provider for provider in PROVIDERS if provider in keys],
            "attempted_providers": attempted_providers,
            "successful_providers": successful_providers,
            "quota_limited_providers": quota_limited_providers,
            "routing": [
                {
                    "query_id": query.query_id,
                    "query": query.query,
                    "intent": query.intent,
                    "language": query.language,
                    "preferred_providers": query.preferred_providers,
                    "providers": providers,
                    "search_mode": search_mode,
                }
                for query, providers in routed_queries
            ],
            "result_count": len(results),
            "results": results,
            "errors": errors,
            "usable": bool(results),
            "fallback_reason": "" if results else "provider_no_results_or_quota",
        }

    def _providers_for_query(
        self,
        query: ProviderQuery,
        keys: dict[ProviderName, str],
        search_mode: SearchMode,
        limit: int,
    ) -> list[ProviderName]:
        if search_mode == "evidence":
            return [provider for provider in _EVIDENCE_PROVIDER_ORDER if provider in keys]
        defaults: dict[str, list[ProviderName]] = {
            "zh": ["bocha", "brave", "tavily"],
            "en": ["exa", "tavily", "brave"],
            "mixed": ["bocha", "tavily", "exa", "brave"],
        }
        ordered = list(dict.fromkeys([*query.preferred_providers, *defaults[query.language], *PROVIDERS]))
        return [provider for provider in ordered if provider in keys][:limit]

    async def _one(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        provider: ProviderName,
        key: str,
        query: ProviderQuery,
        max_results: int,
        country_code: str,
    ) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
        async with semaphore:
            try:
                if provider == "tavily":
                    items = await self._tavily(client, key, query.query, max_results)
                elif provider == "bocha":
                    items = await self._bocha(client, key, query.query, max_results)
                elif provider == "exa":
                    items = await self._exa(client, key, query.query, max_results)
                else:
                    items = await self._brave(client, key, query.query, max_results, country_code)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                return [], {
                    "provider": provider,
                    "query": query.query,
                    "error": _safe_error(exc),
                    "category": "quota_or_auth" if status_code in {401, 403, 429, 432} else "transport_or_response",
                }
        return [
            {
                "query_id": query.query_id,
                "query": query.query,
                "provider": provider,
                "rank": rank,
                **item,
            }
            for rank, item in enumerate(items, start=1)
        ], None

    async def _tavily(self, client: httpx.AsyncClient, key: str, query: str, limit: int) -> list[dict[str, Any]]:
        response = await client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "query": query,
                "search_depth": "advanced",
                "max_results": limit,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        return [
            _item(item, title="title", url="url", snippet="content", date="published_date")
            for item in response.json().get("results", [])[:limit]
        ]

    async def _bocha(self, client: httpx.AsyncClient, key: str, query: str, limit: int) -> list[dict[str, Any]]:
        response = await client.post(
            "https://api.bochaai.com/v1/web-search",
            headers={"Authorization": f"Bearer {key}"},
            json={"query": query, "count": limit, "summary": True},
        )
        response.raise_for_status()
        items = (((response.json().get("data") or {}).get("webPages") or {}).get("value") or [])[:limit]
        return [
            _item(item, title="name", fallback_title="title", url="url", snippet="summary", fallback_snippet="snippet", date="datePublished")
            for item in items
        ]

    async def _exa(self, client: httpx.AsyncClient, key: str, query: str, limit: int) -> list[dict[str, Any]]:
        response = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": key},
            json={"query": query, "numResults": limit, "type": "auto", "contents": {"text": {"maxCharacters": 800}}},
        )
        response.raise_for_status()
        return [
            _item(item, title="title", url="url", snippet="text", date="publishedDate")
            for item in response.json().get("results", [])[:limit]
        ]

    async def _brave(
        self,
        client: httpx.AsyncClient,
        key: str,
        query: str,
        limit: int,
        country_code: str,
    ) -> list[dict[str, Any]]:
        country_code = country_code.upper()
        params: dict[str, Any] = {"q": query, "count": limit}
        if country_code and country_code not in _BRAVE_SKIP_COUNTRY:
            params["country"] = country_code
        search_lang = _BRAVE_SEARCH_LANG.get(country_code)
        if search_lang:
            params["search_lang"] = search_lang
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            params=params,
        )
        response.raise_for_status()
        items = ((response.json().get("web") or {}).get("results") or [])[:limit]
        return [_item(item, title="title", url="url", snippet="description", date="age") for item in items]


def _item(
    item: dict[str, Any],
    *,
    title: str,
    url: str,
    snippet: str,
    date: str,
    fallback_title: str = "",
    fallback_snippet: str = "",
) -> dict[str, Any]:
    compact = " ".join(str(item.get(snippet) or item.get(fallback_snippet) or "").split())
    if len(compact) > 800:
        compact = compact[:799].rstrip() + "…"
    return {
        "title": str(item.get(title) or item.get(fallback_title) or "")[:500],
        "url": str(item.get(url) or ""),
        "snippet": compact,
        "published_date": str(item.get(date) or "")[:100],
    }


def _canonical_url(value: str) -> str:
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        return ""
    url, _ = urldefrag(value)
    return url.rstrip("/")


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__

