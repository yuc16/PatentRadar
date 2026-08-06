import json
from pathlib import Path
from urllib.parse import urlsplit

from starlette.testclient import TestClient

from artifacts import full_claim_chart, report_artifact, task_package, top_competitors
from patentradar_mcp.app import create_app
from patentradar_mcp.config import Settings


def _client(tmp_path: Path, *, search_service=None) -> TestClient:
    app = create_app(
        Settings(
            data_dir=tmp_path,
            public_base_url="http://testserver",
            host="0.0.0.0",
            port=8000,
            debug=False,
        ),
        search_service=search_service,
    )
    return TestClient(app)


def _call_tool(client: TestClient, token: str, name: str, arguments: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    result = client.post("/mcp", headers=headers, json=request).json()["result"]
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def test_tutorial_workspace_and_key_api(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert "搜索自动协同" in client.get("/").text
        workspace = client.post("/api/workspaces")
        assert workspace.status_code == 201
        token = workspace.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        saved = client.put("/api/keys", headers=headers, json={"brave": "brave-user-key"})
        assert saved.status_code == 200
        assert saved.json()["configured"]["brave"] is True
        assert "brave-user-key" not in saved.text

        status = client.get("/api/keys", headers=headers).json()["configured"]
        assert status == {"tavily": False, "bocha": False, "exa": False, "brave": True}


def test_mcp_requires_token_and_exposes_expected_tools(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        assert client.post("/mcp", headers=headers, json=request).status_code == 401

        token = client.post("/api/workspaces").json()["token"]
        headers["Authorization"] = f"Bearer {token}"
        response = client.post("/mcp", headers=headers, json=request)
        assert response.status_code == 200
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert names == {
            "analysis_start",
            "analysis_next",
            "analysis_submit",
            "provider_search",
            "analysis_status",
            "analysis_report",
            "search_key_status",
        }
        start_tool = next(tool for tool in response.json()["result"]["tools"] if tool["name"] == "analysis_start")
        assert set(start_tool["inputSchema"]["properties"]) == {"publication_no"}
        search_tool = next(tool for tool in response.json()["result"]["tools"] if tool["name"] == "provider_search")
        assert "search_mode" in search_tool["inputSchema"]["properties"]
        assert "target_max_results" in search_tool["inputSchema"]["properties"]
        assert "1-200" in search_tool["description"]


def test_mcp_starts_codex_only_case_without_key(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token = client.post("/api/workspaces").json()["token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "analysis_start",
                "arguments": {"publication_no": "CN114512759B"},
            },
        }
        response = client.post("/mcp", headers=headers, json=request).json()["result"]
        assert response["isError"] is False
        assert "module_1_decompose" in response["content"][0]["text"]
        assert "codex_only" in response["content"][0]["text"]


def test_complete_codex_workflow_returns_downloadable_pdf(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token = client.post("/api/workspaces").json()["token"]
        started = _call_tool(
            client,
            token,
            "analysis_start",
            {"publication_no": "CN114512759B"},
        )
        case_id = started["case_id"]
        artifacts = [
            ("module_1_decompose", task_package()),
            ("module_2_competitor_search", top_competitors()),
            ("module_3_full_claim_chart", full_claim_chart()),
            (
                "module_4_report",
                {
                    "report_markdown": "# CN114512759B 专利侵权竞品分析\n\n"
                    + report_artifact()["report_markdown"]
                },
            ),
        ]
        for stage, artifact in artifacts:
            arguments = {"case_id": case_id, "stage": stage, "artifact": artifact}
            if stage in {"module_2_competitor_search", "module_3_full_claim_chart"}:
                arguments["codex_builtin_queries"] = ["示例产品 SKU-1 规格书"]
            submitted = _call_tool(
                client,
                token,
                "analysis_submit",
                arguments,
            )
        assert submitted["completed"] is True

        report = _call_tool(client, token, "analysis_report", {"case_id": case_id})
        parts = urlsplit(report["download_url"])
        downloaded = client.get(f"{parts.path}?{parts.query}")
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"%PDF")


def test_provider_search_accepts_75_items_and_normalizes_query_metadata(tmp_path: Path) -> None:
    observed_queries = []

    class SearchStub:
        async def search(self, **kwargs: object) -> dict:
            queries = list(kwargs["queries"])
            observed_queries.extend(queries)
            return {
                "queries": [query.query for query in queries],
                "query_plan": [query.model_dump(mode="json") for query in queries],
                "search_modes": [str(kwargs["search_mode"])],
                "configured_providers": ["tavily"],
                "attempted_providers": ["tavily"],
                "successful_providers": [],
                "quota_limited_providers": ["tavily"],
                "routing": [],
                "result_count": 0,
                "results": [],
                "errors": [],
                "usable": False,
                "fallback_reason": "provider_no_results_or_quota",
            }

    with _client(tmp_path, search_service=SearchStub()) as client:
        token = client.post("/api/workspaces").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        client.put("/api/keys", headers=headers, json={"tavily": "user-key"})
        started = _call_tool(client, token, "analysis_start", {"publication_no": "CN114512759B"})
        case_id = started["case_id"]
        _call_tool(
            client,
            token,
            "analysis_submit",
            {"case_id": case_id, "stage": "module_1_decompose", "artifact": task_package()},
        )
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

        searched = _call_tool(
            client,
            token,
            "provider_search",
            {"case_id": case_id, "queries": queries, "search_mode": "evidence"},
        )

        assert len(searched["queries"]) == 75
        assert len(observed_queries) == 75
        assert observed_queries[0].query_id == "Q001"
        assert observed_queries[-1].query_id == "Q075"
        assert {query.intent for query in observed_queries} == {"evidence"}


def test_configured_key_enables_hybrid_search_and_keeps_codex_required(tmp_path: Path) -> None:
    class SearchStub:
        async def search(self, **kwargs: object) -> dict:
            search_mode = str(kwargs["search_mode"])
            return {
                "queries": ["产品 规格书"],
                "query_plan": [],
                "search_modes": [search_mode],
                "configured_providers": ["tavily"],
                "attempted_providers": ["tavily"],
                "successful_providers": ["tavily"],
                "quota_limited_providers": [],
                "routing": [{"query_id": "Q01", "query": "产品 规格书", "providers": ["tavily"]}],
                "result_count": 1,
                "results": [{"url": "https://example.com/provider-spec", "provider": "tavily"}],
                "errors": [],
                "usable": True,
                "fallback_reason": "",
            }

    with _client(tmp_path, search_service=SearchStub()) as client:
        token = client.post("/api/workspaces").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.put("/api/keys", headers=headers, json={"tavily": "user-key"}).status_code == 200

        started = _call_tool(client, token, "analysis_start", {"publication_no": "CN114512759B"})
        assert started["search_strategy"] == "codex_only"
        case_id = started["case_id"]
        _call_tool(
            client,
            token,
            "analysis_submit",
            {
                "case_id": case_id,
                "stage": "module_1_decompose",
                "artifact": task_package(),
            },
        )
        next_step = _call_tool(client, token, "analysis_next", {"case_id": case_id})
        assert next_step["search_strategy"] == "hybrid_pending"

        searched = _call_tool(
            client,
            token,
            "provider_search",
            {"case_id": case_id, "queries": ["产品 规格书"], "search_mode": "discovery"},
        )
        assert searched["result_count"] == 1
        searched = _call_tool(
            client,
            token,
            "provider_search",
            {"case_id": case_id, "queries": ["产品 维修手册"], "search_mode": "evidence"},
        )
        assert searched["search_modes"] == ["discovery", "evidence"]
        evidence_step = _call_tool(client, token, "analysis_next", {"case_id": case_id})
        assert evidence_step["search_strategy"] == "hybrid"
        assert evidence_step["provider_search"]["result_count"] == 1
        assert "Codex 内置网页搜索" in evidence_step["instruction"]
