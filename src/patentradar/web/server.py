"""PatentRadar Web 仪表盘后端。

职责：
1. 把项目根目录下 ``web/`` 静态站点 mount 到 ``/``
2. 暴露 4 个 API：
   - ``GET  /api/patents``                            扫描 ``output/`` 列出有 log 的专利
   - ``GET  /api/patents/{pub_no}/events``            一次性返回完整历史事件（首屏快速重建时间轴）
   - ``GET  /api/patents/{pub_no}/stream``            SSE 增量推送（active run 才会持续推；已结束 run 立即结束）
   - ``GET  /api/patents/{pub_no}/artifacts``         列出可用产物
   - ``GET  /api/patents/{pub_no}/artifacts/{name}``  返回产物内容（md / json）
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from . import log_parser

logger = logging.getLogger("patentradar.web")

ARTIFACT_FILES: dict[str, tuple[str, str]] = {
    # id -> (relative path under tmp/<pub>/, mime)
    "task_package":   ("task_package.json",   "application/json"),
    "candidate_pool": ("candidate_pool.json", "application/json"),
    "agent_outputs":  ("agent_outputs.json",  "application/json"),
    "final_report_json": ("final_report.json", "application/json"),
    "final_report_md":   ("final_report.md",   "text/markdown"),
}
# 在 output/<pub>/ 下找最终 markdown
FINAL_MD_FROM_OUTPUT = ("final_report.md", "text/markdown")


def _project_root() -> Path:
    return config.PROJECT_ROOT


def _web_dir() -> Path:
    return _project_root() / "web"


def _output_root() -> Path:
    return config.OUTPUT_DIR


def _intermediate_root() -> Path:
    return config.INTERMEDIATE_DIR


def create_app() -> FastAPI:
    app = FastAPI(title="PatentRadar Dashboard", version="0.1.0")

    @app.get("/api/patents")
    def list_patents() -> list[dict]:
        return log_parser.list_patent_runs(_output_root())

    @app.get("/api/current-run")
    def current_run() -> dict:
        """返回项目中**最新一次** run 的元信息；没有 log 则返回 ``{has_run: false}``。

        前端只展示这一次。"""
        info = log_parser.get_current_run(_output_root())
        if info is None:
            return {"has_run": False}
        return {"has_run": True, **info}

    @app.get("/api/patents/{pub_no}/events")
    def patent_events(pub_no: str) -> dict:
        pub_dir = _output_root() / pub_no
        log_path = log_parser.find_competitors_log(pub_dir)
        if not log_path:
            raise HTTPException(404, f"未找到 {pub_no} 的 log 文件")
        events = [e.to_dict() for e in log_parser.iter_events([log_path])]
        size_now = log_path.stat().st_size
        return {
            "pub_no": pub_no,
            "log_path": str(log_path.relative_to(_project_root())),
            "events": events,
            "byte_offset": size_now,  # 客户端用此 offset 走 SSE 拿增量
            "is_active": _is_active_run(log_path),
        }

    @app.get("/api/patents/{pub_no}/stream")
    async def patent_stream(pub_no: str, offset: int = 0, request: Request = None):
        pub_dir = _output_root() / pub_no
        log_path = log_parser.find_competitors_log(pub_dir)
        if not log_path:
            raise HTTPException(404, f"未找到 {pub_no} 的 log 文件")

        async def gen() -> AsyncIterator[str]:
            current_offset = offset
            idle_ticks = 0
            t_base_state: dict[str, float | None] = {"t": None}
            # 初始状态：找到当前文件首行的 t_base，确保增量事件 t 与 /events 对齐
            with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                line = fh.readline()
                while line:
                    ev, t_base_state["t"] = log_parser.parse_line(
                        line, t_base=t_base_state["t"]
                    )
                    if t_base_state["t"] is not None:
                        break
                    line = fh.readline()

            while True:
                if request is not None and await request.is_disconnected():
                    return
                size = log_path.stat().st_size
                if size > current_offset:
                    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(current_offset)
                        new_chunk = fh.read()
                        current_offset = fh.tell()
                    for raw in new_chunk.splitlines(keepends=False):
                        ev, t_base_state["t"] = log_parser.parse_line(
                            raw + "\n", t_base=t_base_state["t"]
                        )
                        if ev is not None:
                            yield f"event: log\ndata: {json.dumps(ev.to_dict(), ensure_ascii=False)}\n\n"
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    # 心跳，避免代理 / 浏览器超时
                    yield ": ping\n\n"

                # 已结束 run（mtime > 30s 没动 → 跳出）
                if not _is_active_run(log_path) and idle_ticks > 2:
                    yield "event: end\ndata: {}\n\n"
                    return
                await asyncio.sleep(1.0)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/patents/{pub_no}/artifacts")
    def artifacts_list(pub_no: str, since: float | None = None) -> list[dict]:
        """列出该 patent 的产物。

        - 若 ``since`` 给定（unix timestamp），**只把 mtime ≥ since 的标 ready=True**；
          老产物（属于上一次 run）视为 ready=False 灰色显示，避免误导。
        - 不传 since 则全部 ready（兼容老调用）。

        永远返回**全部 5 类产物**（task_package / candidate_pool / agent_outputs /
        final_report.json / final_report.md），未生成的 ready=False。
        """
        tmp_dir = _intermediate_root() / pub_no
        out_dir = _output_root() / pub_no
        items: list[dict] = []
        for art_id, (filename, mime) in ARTIFACT_FILES.items():
            p = tmp_dir / filename
            if not p.exists() and art_id == "final_report_md":
                p = out_dir / filename
            ready = False
            mtime = None
            if p.exists():
                mtime = p.stat().st_mtime
                if since is None or mtime >= since:
                    ready = True
            items.append({
                "id": art_id,
                "name": _artifact_display_name(art_id),
                "filename": filename,
                "mime": mime,
                "ready": ready,
                "mtime": mtime,
            })
        return items

    @app.get("/api/patents/{pub_no}/artifacts/{art_id}")
    def artifact_content(pub_no: str, art_id: str):
        if art_id not in ARTIFACT_FILES:
            raise HTTPException(404, f"未知 artifact id: {art_id}")
        filename, mime = ARTIFACT_FILES[art_id]
        # 优先 tmp/，fallback output/（仅 final_report.md 在 output 下）
        p = _intermediate_root() / pub_no / filename
        if not p.exists():
            p2 = _output_root() / pub_no / filename
            if p2.exists():
                p = p2
            else:
                raise HTTPException(404, f"未找到产物: {filename}")
        if mime == "application/json":
            text = p.read_text(encoding="utf-8")
            return PlainTextResponse(text, media_type="application/json")
        return FileResponse(p, media_type=mime)

    # 静态前端
    web_dir = _web_dir()
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    else:
        @app.get("/")
        def _root():
            return PlainTextResponse(
                f"web/ 目录不存在: {web_dir}\n请先创建前端静态文件",
                status_code=500,
            )
    return app


def _artifact_display_name(art_id: str) -> str:
    return {
        "task_package":      "任务包 · 权利要求拆解",
        "candidate_pool":    "候选竞品池（合并前快照）",
        "agent_outputs":     "三 Agent 原始输出汇总",
        "final_report_json": "最终复核报告（JSON）",
        "final_report_md":   "最终复核报告（Markdown）",
    }.get(art_id, art_id)


_ACTIVE_RUN_GRACE_SECONDS = 300  # 单次 LLM 调用最长 ~3min，留 5min 余量


def _is_active_run(log_path: Path) -> bool:
    """log 文件 mtime 在 ``_ACTIVE_RUN_GRACE_SECONDS`` 内 → 视为仍在写入。

    阈值要覆盖单次 LLM 调用的最大无日志间隔（query 生成 / candidate_filter /
    feature_match 都可能 60~180s 不写日志），否则会误判为已结束。
    """
    import time
    return (time.time() - log_path.stat().st_mtime) < _ACTIVE_RUN_GRACE_SECONDS


# 给 uvicorn 直接调用
app = create_app()


def main(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    import uvicorn
    if reload:
        uvicorn.run("patentradar.web.server:app", host=host, port=port, reload=True)
    else:
        uvicorn.run(create_app(), host=host, port=port)
