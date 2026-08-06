from __future__ import annotations

import contextvars
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .config import Settings
from .models import KeyUpdate, PROVIDERS, ProviderSearchInput, SearchMode, StartAnalysisInput, WorkSubmission
from .report import render_report
from .search import ProviderSearchService
from .security import SecretBox
from .store import Store
from .workflow import (
    STAGES,
    current_work_item,
    effective_search_strategy,
    normalize_submission_artifact,
    validate_submission,
)


_workspace_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "patentradar_workspace", default=None
)

INSTRUCTIONS = (
    "PatentRadar 严格按四个独立 subagent 串行执行：权利要求拆解 → 竞品搜索与权1判定 → 全部权利要求 Claim Chart → 报告。"
    "先调用 analysis_start，再反复调用 analysis_next 获取当前模块的完整规则和输入；完整执行后用 analysis_submit 提交。"
    "主 Codex 只负责编排、提交和处理校验错误；每个模块必须派生一个新的独立 subagent 执行，不得把四个模块合并到一次推理。"
    "模块二和三始终使用 Codex 内置网页搜索、页面读取和视觉能力；配置搜索 Key 时同时调用 provider_search，"
    "把 Tavily/Bocha/Exa/Brave 结果与内置搜索合并。外部搜索失败时继续 Codex，不得降低分析标准。"
    "最终调用 analysis_report 获取 PDF。不要索要、读取或传递 ChatGPT 登录凭证和搜索 Key。"
)


class WorkspaceAuthMiddleware:
    def __init__(self, app: Any, store: Store) -> None:
        self.app = app
        self.store = store

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = str(scope.get("path") or "")
        if scope.get("type") == "http" and path.rstrip("/") == "/mcp":
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            authorization = headers.get(b"authorization", b"").decode("latin-1")
            token = authorization.removeprefix("Bearer ").strip()
            workspace_id = self.store.authenticate(token)
            if workspace_id is None:
                response = JSONResponse(
                    {"error": "unauthorized", "message": "请先在教程页创建工作区令牌"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
            context_token = _workspace_context.set(workspace_id)
            try:
                await self.app(scope, receive, send)
            finally:
                _workspace_context.reset(context_token)
            return
        await self.app(scope, receive, send)


def _workspace_id() -> str:
    workspace_id = _workspace_context.get()
    if workspace_id is None:
        raise ToolError("当前 MCP 请求缺少有效工作区身份")
    return workspace_id


def _tool_error(exc: Exception) -> ToolError:
    if isinstance(exc, ValidationError):
        message = exc.errors()[0].get("msg", "参数校验失败")
    else:
        message = str(exc)
    return ToolError(message)


def create_app(
    settings: Settings | None = None,
    *,
    search_service: ProviderSearchService | None = None,
) -> Any:
    settings = settings or Settings.from_env()
    secret_box = SecretBox.load(settings.data_dir)
    store = Store(settings.data_dir / "patentradar-mcp.sqlite3", secret_box)
    search_service = search_service or ProviderSearchService()
    web_dir = Path(__file__).parent / "web"

    server = FastMCP(
        "PatentRadar",
        instructions=INSTRUCTIONS,
        website_url=settings.public_base_url,
        host=settings.host,
        port=settings.port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        debug=settings.debug,
    )

    @server.tool(
        title="开始专利分析",
        description="用户给出专利公开号并要求开始分析时调用。搜索策略会根据当前工作区的 Key 自动选择。",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    async def analysis_start(publication_no: str) -> dict[str, Any]:
        workspace_id = _workspace_id()
        try:
            data = StartAnalysisInput(publication_no=publication_no)
            case = store.create_case(workspace_id, data.publication_no)
            has_keys = any(store.key_status(workspace_id).values())
            return {
                "case_id": case["id"],
                "publication_no": case["publication_no"],
                "search_strategy": effective_search_strategy(case, provider_keys_available=has_keys),
                "next": current_work_item(case, provider_keys_available=has_keys),
            }
        except (ValidationError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        title="获取下一项分析任务",
        description="开始案件后反复调用，获取当前阶段及输入材料；不会返回搜索 Key。",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    async def analysis_next(case_id: str) -> dict[str, Any]:
        try:
            workspace_id = _workspace_id()
            case = store.get_case(workspace_id, case_id)
            has_keys = any(store.key_status(workspace_id).values())
            return current_work_item(case, provider_keys_available=has_keys)
        except KeyError as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        title="提交阶段分析结果",
        description="把 analysis_next 指定阶段的结构化 artifact 提交给服务器校验并保存。",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    async def analysis_submit(
        case_id: str,
        stage: str,
        artifact: dict[str, Any],
        codex_builtin_queries: list[str] | None = None,
    ) -> dict[str, Any]:
        workspace_id = _workspace_id()
        try:
            submission = WorkSubmission(
                case_id=case_id,
                stage=stage,
                artifact=normalize_submission_artifact(stage, artifact),
            )
            case = store.get_case(workspace_id, submission.case_id)
            has_keys = any(store.key_status(workspace_id).values())
            next_index, completed = validate_submission(
                case,
                submission.stage,
                submission.artifact,
                provider_keys_available=has_keys,
            )
            if submission.stage in {STAGES[1].name, STAGES[2].name}:
                cleaned_queries = list(
                    dict.fromkeys(
                        query.strip()[:500]
                        for query in (codex_builtin_queries or [])
                        if isinstance(query, str) and len(query.strip()) >= 2
                    )
                )
                if not cleaned_queries:
                    raise ValueError("模块二和三必须提交实际使用过的 Codex 内置搜索查询 codex_builtin_queries")
                case = store.save_search_audit(
                    workspace_id,
                    submission.case_id,
                    stage=submission.stage,
                    codex_builtin_queries=cleaned_queries,
                )
            case = store.save_artifact(
                workspace_id,
                submission.case_id,
                stage=submission.stage,
                artifact=submission.artifact,
                next_stage_index=next_index,
                completed=completed,
            )
            if completed:
                render_report(
                    publication_no=case["publication_no"],
                    markdown_text=submission.artifact["report_markdown"],
                    output_dir=_report_dir(settings, workspace_id, case_id),
                )
            return {
                "accepted": True,
                "completed": completed,
                "next": current_work_item(case, provider_keys_available=has_keys),
            }
        except (ValidationError, ValueError, KeyError, OSError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        title="使用自备 Key 搜索证据",
        description="使用用户自备 Key 并发调用 Tavily、Bocha、Exa 或 Brave。每次接受1-200条 query，服务器自动编号、去重并规范未知 intent。discovery 尊重 preferred_providers 且每条最多3源；evidence 调用全部已配置源。结果交给本地 Codex 做语义过滤、验活和跨源合并。",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    )
    async def provider_search(
        case_id: str,
        queries: list[str | dict[str, Any]],
        search_mode: SearchMode = "discovery",
        max_results_per_provider: int = 5,
        max_providers_per_query: int = 3,
        target_max_results: int = 400,
    ) -> dict[str, Any]:
        workspace_id = _workspace_id()
        try:
            data = ProviderSearchInput(
                case_id=case_id,
                queries=queries,
                search_mode=search_mode,
                max_results_per_provider=max_results_per_provider,
                max_providers_per_query=max_providers_per_query,
                target_max_results=target_max_results,
            )
            case = store.get_case(workspace_id, data.case_id)
            stage_index = int(case["stage_index"])
            if stage_index not in {1, 2}:
                raise ValueError("provider_search 仅在模块二竞品搜索和模块三缺口补搜阶段调用")
            stage_name = STAGES[stage_index].name
            keys = store.decrypted_keys(workspace_id)
            task_package = (case.get("artifacts") or {}).get(STAGES[0].name) or {}
            country_code = str((task_package.get("patent") or {}).get("country_code") or "")
            results = await search_service.search(
                queries=data.queries,
                keys=keys,
                max_results=data.max_results_per_provider,
                search_mode=data.search_mode,
                max_providers_per_query=data.max_providers_per_query,
                target_max_results=data.target_max_results,
                country_code=country_code,
            )
            updated_case = store.save_search_results(
                workspace_id,
                data.case_id,
                results,
                stage=stage_name,
            )
            return updated_case["artifacts"]["_provider_search"][stage_name]
        except (ValidationError, ValueError, KeyError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        title="查询分析进度",
        description="查看案件当前阶段、已完成阶段和状态，不返回完整材料。",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    async def analysis_status(case_id: str) -> dict[str, Any]:
        try:
            workspace_id = _workspace_id()
            case = store.get_case(workspace_id, case_id)
            has_keys = any(store.key_status(workspace_id).values())
            completed_stages = [stage.name for stage in STAGES if stage.name in case["artifacts"]]
            return {
                "case_id": case["id"],
                "publication_no": case["publication_no"],
                "search_strategy": effective_search_strategy(case, provider_keys_available=has_keys),
                "provider_keys_configured": has_keys,
                "status": case["status"],
                "completed_stages": completed_stages,
                "current_stage": STAGES[case["stage_index"]].name if case["stage_index"] < len(STAGES) else None,
                "updated_at": case["updated_at"],
            }
        except KeyError as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        title="获取分析 PDF",
        description="案件完成后返回 15 分钟有效的 PDF 下载地址。",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    async def analysis_report(case_id: str) -> dict[str, Any]:
        workspace_id = _workspace_id()
        try:
            case = store.get_case(workspace_id, case_id)
            if case["status"] != "completed":
                raise ValueError("报告尚未完成")
            pdf_path = _pdf_path(settings, workspace_id, case)
            if not pdf_path.is_file():
                report_artifact = case["artifacts"].get(STAGES[3].name) or {}
                render_report(
                    publication_no=case["publication_no"],
                    markdown_text=str(report_artifact.get("report_markdown") or ""),
                    output_dir=_report_dir(settings, workspace_id, case_id),
                )
            access = secret_box.sign_download(workspace_id=workspace_id, case_id=case_id)
            url = (
                f"{settings.public_base_url}/reports/{quote(case_id)}.pdf"
                f"?workspace={quote(workspace_id)}&access={quote(access)}"
            )
            return {"case_id": case_id, "publication_no": case["publication_no"], "download_url": url, "expires_in_seconds": 900}
        except (KeyError, ValueError, OSError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        title="查询搜索 Key 配置状态",
        description="只返回四个平台是否已配置，绝不返回 Key 内容。",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    async def search_key_status() -> dict[str, bool]:
        return store.key_status(_workspace_id())

    @server.custom_route("/", methods=["GET"], include_in_schema=False)
    async def tutorial(_: Request) -> Response:
        return HTMLResponse((web_dir / "index.html").read_text(encoding="utf-8"))

    @server.custom_route("/assets/styles.css", methods=["GET"], include_in_schema=False)
    async def styles(_: Request) -> Response:
        return FileResponse(web_dir / "styles.css", media_type="text/css")

    @server.custom_route("/assets/app.js", methods=["GET"], include_in_schema=False)
    async def javascript(_: Request) -> Response:
        return FileResponse(web_dir / "app.js", media_type="text/javascript")

    @server.custom_route("/assets/favicon.svg", methods=["GET"], include_in_schema=False)
    async def favicon(_: Request) -> Response:
        return FileResponse(web_dir / "favicon.svg", media_type="image/svg+xml")

    @server.custom_route("/api/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "PatentRadar MCP", "version": "1.0.0"})

    @server.custom_route("/api/workspaces", methods=["POST"], include_in_schema=False)
    async def create_workspace(_: Request) -> Response:
        workspace_id, token = store.create_workspace()
        return JSONResponse(
            {
                "workspace_id": workspace_id,
                "token": token,
                "mcp_url": f"{settings.public_base_url}/mcp",
                "message": "令牌只展示一次，请妥善保存。",
            },
            status_code=201,
        )

    @server.custom_route("/api/keys", methods=["GET", "PUT", "DELETE"], include_in_schema=False)
    async def keys_api(request: Request) -> Response:
        workspace_id = _authenticate_request(request, store)
        if workspace_id is None:
            return _unauthorized()
        if request.method == "GET":
            return JSONResponse({"configured": store.key_status(workspace_id)})
        if request.method == "DELETE":
            provider = request.query_params.get("provider", "")
            if provider not in PROVIDERS:
                return JSONResponse({"error": "无效搜索平台"}, status_code=400)
            store.delete_key(workspace_id, provider)  # type: ignore[arg-type]
            return JSONResponse({"configured": store.key_status(workspace_id)})
        try:
            payload = KeyUpdate.model_validate(await request.json())
            supplied = payload.supplied()
            if not supplied:
                return JSONResponse({"error": "至少填写一个非空 Key"}, status_code=400)
            status = store.update_keys(workspace_id, supplied)
            return JSONResponse({"configured": status, "message": "Key 已加密保存，接口不会返回原值。"})
        except (ValidationError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @server.custom_route("/reports/{case_id}.pdf", methods=["GET"], include_in_schema=False)
    async def download_report(request: Request) -> Response:
        case_id = request.path_params["case_id"]
        workspace_id = request.query_params.get("workspace", "")
        access = request.query_params.get("access", "")
        if not secret_box.verify_download(access, workspace_id=workspace_id, case_id=case_id):
            return JSONResponse({"error": "下载地址无效或已过期"}, status_code=403)
        try:
            case = store.get_case(workspace_id, case_id)
        except KeyError:
            return JSONResponse({"error": "报告不存在"}, status_code=404)
        path = _pdf_path(settings, workspace_id, case)
        if not path.is_file():
            return JSONResponse({"error": "报告文件不存在"}, status_code=404)
        return FileResponse(path, media_type="application/pdf", filename=f"{case['publication_no']}-PatentRadar.pdf")

    app = server.streamable_http_app()
    app.add_middleware(WorkspaceAuthMiddleware, store=store)
    app.state.patentradar_store = store
    app.state.patentradar_server = server
    return app


def _authenticate_request(request: Request, store: Store) -> str | None:
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").strip()
    return store.authenticate(token)


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": "工作区令牌无效"},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _report_dir(settings: Settings, workspace_id: str, case_id: str) -> Path:
    return settings.data_dir / "reports" / workspace_id / case_id


def _pdf_path(settings: Settings, workspace_id: str, case: dict[str, Any]) -> Path:
    safe_name = "".join(character for character in case["publication_no"] if character.isalnum())
    return _report_dir(settings, workspace_id, case["id"]) / f"{safe_name}.pdf"


app = create_app()


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "patentradar_mcp.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
