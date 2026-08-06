import asyncio

import httpx
import pytest

from patentradar_mcp.search import ProviderSearchService
from patentradar_mcp.models import ProviderQuery, ProviderSearchInput


def _query(
    query_id: str,
    query: str,
    *,
    language: str = "mixed",
    preferred_providers: list[str] | None = None,
) -> ProviderQuery:
    return ProviderQuery.model_validate(
        {
            "query_id": query_id,
            "query": query,
            "intent": "evidence",
            "language": language,
            "preferred_providers": preferred_providers or [],
        }
    )


def test_provider_search_input_accepts_and_normalizes_75_query_plan_items() -> None:
    queries = [
        {
            "query_id": f"M3-Q{index:03d}",
            "query": f"SKU-{index} battery teardown dimensions",
            "intent": "evidence_dimensions_structure",
            "language": "en",
            "preferred_providers": ["exa", "tavily", "brave"],
        }
        for index in range(1, 76)
    ]

    data = ProviderSearchInput(case_id="case_1", queries=queries, search_mode="evidence")

    assert len(data.queries) == 75
    assert data.queries[0].query_id == "Q001"
    assert data.queries[-1].query_id == "Q075"
    assert {query.intent for query in data.queries} == {"evidence"}


def test_provider_search_input_deduplicates_query_text_and_infers_metadata() -> None:
    data = ProviderSearchInput(
        case_id="case_1",
        queries=[
            {"query": "  产品规格书  ", "query_id": "invalid", "intent": "custom"},
            {"query": "产品规格书", "query_id": "also-invalid"},
        ],
    )

    assert len(data.queries) == 1
    assert data.queries[0].query_id == "Q001"
    assert data.queries[0].intent == "evidence"
    assert data.queries[0].language == "zh"


@pytest.mark.asyncio
async def test_tavily_search_normalizes_and_deduplicates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer user-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "规格书", "url": "https://example.com/spec#top", "content": "尺寸参数"},
                    {"title": "重复", "url": "https://example.com/spec", "content": "同页"},
                ]
            },
        )

    service = ProviderSearchService(transport=httpx.MockTransport(handler))
    result = await service.search(
        queries=[_query("Q01", "产品 规格书", language="zh")],
        keys={"tavily": "user-key"},
        max_results=5,
    )

    assert result["configured_providers"] == ["tavily"]
    assert result["result_count"] == 1
    assert result["results"][0]["url"] == "https://example.com/spec"


@pytest.mark.asyncio
async def test_provider_errors_do_not_expose_key() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid secret-user-key")

    service = ProviderSearchService(transport=httpx.MockTransport(handler))
    result = await service.search(
        queries=[_query("Q01", "测试", language="zh")],
        keys={"tavily": "secret-user-key"},
        max_results=5,
    )

    assert result["results"] == []
    assert result["errors"][0]["error"] == "HTTP 401"
    assert result["quota_limited_providers"] == ["tavily"]
    assert result["fallback_reason"] == "provider_no_results_or_quota"
    assert "secret-user-key" not in str(result)


@pytest.mark.asyncio
async def test_discovery_respects_query_plan_preference_and_language_defaults() -> None:
    called_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_hosts.append(request.url.host)
        if request.url.host == "api.bochaai.com":
            return httpx.Response(200, json={"data": {"webPages": {"value": []}}})
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, json={"web": {"results": []}})
        return httpx.Response(200, json={"results": []})

    service = ProviderSearchService(transport=httpx.MockTransport(handler))
    result = await service.search(
        queries=[
            _query("Q01", "产品 规格 参数", language="zh", preferred_providers=["brave", "bocha"]),
            _query("Q02", "product datasheet dimensions", language="en"),
        ],
        keys={"tavily": "t", "bocha": "b", "exa": "e", "brave": "r"},
        max_results=3,
        search_mode="discovery",
    )

    assert result["routing"][0]["providers"] == ["brave", "bocha", "tavily"]
    assert result["routing"][1]["providers"] == ["exa", "tavily", "brave"]
    assert called_hosts.count("api.exa.ai") == 1
    assert called_hosts.count("api.bochaai.com") == 1


@pytest.mark.asyncio
async def test_only_configured_provider_is_used_even_when_not_preferred() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.exa.ai"
        return httpx.Response(200, json={"results": []})

    service = ProviderSearchService(transport=httpx.MockTransport(handler))
    result = await service.search(
        queries=[_query("Q01", "产品 拆解 评测", language="zh")],
        keys={"exa": "e"},
        max_results=3,
    )

    assert result["routing"][0]["providers"] == ["exa"]
    assert result["attempted_providers"] == ["exa"]


@pytest.mark.asyncio
async def test_evidence_mode_uses_all_configured_providers_in_src_order() -> None:
    called_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_hosts.append(request.url.host)
        if request.url.host == "api.bochaai.com":
            return httpx.Response(200, json={"data": {"webPages": {"value": []}}})
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, json={"web": {"results": []}})
        return httpx.Response(200, json={"results": []})

    service = ProviderSearchService(transport=httpx.MockTransport(handler))
    result = await service.search(
        queries=[_query("Q01", "候选产品维修手册", language="zh")],
        keys={"tavily": "t", "bocha": "b", "exa": "e", "brave": "r"},
        max_results=3,
        search_mode="evidence",
    )

    assert result["routing"][0]["providers"] == ["bocha", "brave", "tavily", "exa"]
    assert result["search_modes"] == ["evidence"]
    assert len(called_hosts) == 4


@pytest.mark.asyncio
async def test_brave_receives_patent_country_and_language_hints() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["country"] == "CN"
        assert request.url.params["search_lang"] == "zh-hans"
        return httpx.Response(200, json={"web": {"results": []}})

    service = ProviderSearchService(transport=httpx.MockTransport(handler))
    await service.search(
        queries=[_query("Q01", "产品参数", language="zh")],
        keys={"brave": "r"},
        max_results=3,
        country_code="CN",
    )


@pytest.mark.asyncio
async def test_external_providers_are_actually_called_concurrently() -> None:
    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        if request.url.host == "api.bochaai.com":
            return httpx.Response(200, json={"data": {"webPages": {"value": []}}})
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, json={"web": {"results": []}})
        return httpx.Response(200, json={"results": []})

    service = ProviderSearchService(transport=httpx.MockTransport(handler))
    await service.search(
        queries=[_query("Q01", "候选产品证据", language="zh")],
        keys={"tavily": "t", "bocha": "b", "exa": "e", "brave": "r"},
        max_results=3,
        search_mode="evidence",
    )

    assert peak == 4
