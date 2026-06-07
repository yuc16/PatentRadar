"""FastAPI dashboard app for PatentRadar.

Endpoints
---------
GET  /                             → web/index.html (mounted via StaticFiles)
POST /api/run/{pub}                → kick off the 4-module pipeline (background)
GET  /api/status/{pub}             → JSON status snapshot (poll-friendly)
GET  /api/stream/{pub}             → SSE stream of run events + token deltas
GET  /api/log/{pub}/{module}?tail= → tail N lines of module_<n>.log
GET  /api/output/{pub}/{file}      → raw read-through of data/output artifacts

Run:
    uvicorn patentradar.server.app:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from patentradar.core.exceptions import PatentFetchError
from patentradar.fetcher.google_patents import normalize_publication_no
from patentradar.server.runner import (
    DATA_OUTPUT,
    LOGS_ROOT,
    ROOT,
    iter_run_events,
    run_and_release,
    try_begin_run,
)

# Load .env from project root so subprocess env inherits API keys etc.
load_dotenv(ROOT / ".env")

app = FastAPI(title="PatentRadar Dashboard")

WEB_DIR = ROOT / "web"

# pipeline_end 后 SSE 循环继续轮询多少轮（每轮 0.4s）再退出，让收尾的 token
# delta / stdout 行有时间落到 stream.jsonl / module.log 再被 tail 出去。
# 3 轮 ≈ 1.2s 经验值：覆盖大多数 stdout flush 抖动；容器或慢盘环境如果观察到
# 报告末尾 token 偶发被截，调到 5。继续往上调代价是 SSE 协程多挂 N×0.4s。
_SSE_TRAILING_ROUNDS_AFTER_END = 3


# ---------- helpers ----------------------------------------------------------


def _publication_root(pub: str) -> Path:
    # Mild sanity guard against path traversal — publication numbers are
    # always alphanumeric (e.g. CN114512759B).
    if not pub or not pub.replace("/", "").replace("\\", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid publication_no")
    return DATA_OUTPUT / pub


def _safe_resolve(root: Path, filename: str) -> Path:
    """Resolve `root / filename` and enforce that it stays inside `root`.

    用 Path.relative_to 而不是 str.startswith：startswith 在 root 名是兄弟目录
    前缀时会被绕过（root=/x/AB，filename='../ABC/secret' → /x/ABC/secret 也
    "startswith /x/AB" 为 True）。
    """
    target = (root / filename).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid path") from exc
    return target


def _module_output_summary(pub: str) -> dict[int, dict]:
    """Inspect data/output/<pub>/ and extract per-module key metrics."""
    root = _publication_root(pub)
    summary: dict[int, dict] = {}

    tp = root / "task_package.json"
    if tp.exists():
        try:
            data = json.loads(tp.read_text(encoding="utf-8"))
            patent = data.get("patent") or {}
            claims = data.get("claims") or []
            c1_features = claims[0].get("features") if claims else []
            summary[1] = {
                "title": patent.get("title", ""),
                "publication_no": patent.get("publication_no", ""),
                "applicants": patent.get("applicants", []),
                "application_date": patent.get("application_date", ""),
                "technology_tag": data.get("technology_tag", ""),
                "claims": len(claims),
                "claim1_features": len(c1_features or []),
                "files": [{"name": "task_package.json", "kind": "json"}],
            }
        except Exception:  # noqa: BLE001
            summary[1] = {"error": "task_package.json unparseable"}

    top = root / "step5_top5_claim1_candidates.json"
    if top.exists():
        try:
            data = json.loads(top.read_text(encoding="utf-8"))
            top_list = data.get("top_competitors") or []
            exc_list = data.get("excluded_candidates") or []
            top_summary = []
            for cc in top_list:
                cand = cc.get("candidate") or {}
                top_summary.append({
                    "candidate_id": cand.get("candidate_id"),
                    "company": cand.get("company"),
                    "product_name": cand.get("product_name"),
                    "total_score": cc.get("total_score"),
                })
            summary[2] = {
                "top_count": len(top_list),
                "excluded_count": len(exc_list),
                "top": top_summary,
                "files": [{"name": "step5_top5_claim1_candidates.json", "kind": "json"}],
            }
        except Exception:  # noqa: BLE001
            summary[2] = {"error": "step5 file unparseable"}

    chart = root / "top5_full_claim_chart.json"
    if chart.exists():
        try:
            data = json.loads(chart.read_text(encoding="utf-8"))
            entries = data.get("top_competitors") or []
            chart_summary = []
            for e in entries:
                cand = e.get("candidate") or {}
                chart_summary.append({
                    "candidate_id": cand.get("candidate_id"),
                    "company": cand.get("company"),
                    "total_score": e.get("total_score"),
                    "claim_1_score": e.get("claim_1_score"),
                })
            summary[3] = {
                "candidates": chart_summary,
                "candidate_count": len(entries),
                "files": [{"name": "top5_full_claim_chart.json", "kind": "json"}],
            }
        except Exception:  # noqa: BLE001
            summary[3] = {"error": "full_claim_chart unparseable"}

    report_md = root / "report.md"
    report_pdf = root / "report.pdf"
    if report_md.exists():
        files = [{"name": "report.md", "kind": "md"}]
        if report_pdf.exists():
            files.append({"name": "report.pdf", "kind": "pdf"})
        summary[4] = {
            "report_md": str(report_md.relative_to(ROOT)),
            "report_pdf": str(report_pdf.relative_to(ROOT)) if report_pdf.exists() else None,
            "size_bytes": report_md.stat().st_size,
            "files": files,
        }

    return summary


def _module_status(pub: str) -> list[dict]:
    """Walk run.jsonl and derive {status, elapsed} per module."""
    events = list(iter_run_events(pub))
    module_state: dict[int, dict] = {}
    for ev in events:
        n = ev.get("module")
        if n is None:
            continue
        state = module_state.setdefault(n, {"id": n, "status": "pending", "elapsed_s": None})
        if ev.get("event") == "start":
            state["status"] = "running"
            state["started_ts"] = ev.get("ts")
        elif ev.get("event") == "done":
            state["status"] = "done"
            state["elapsed_s"] = ev.get("elapsed")
        elif ev.get("event") == "error":
            state["status"] = "error"
            state["elapsed_s"] = ev.get("elapsed")
            state["error"] = ev.get("message") or f"exit_code={ev.get('exit_code')}"

    result = []
    for n in (1, 2, 3, 4):
        s = module_state.get(n) or {"id": n, "status": "pending", "elapsed_s": None}
        result.append(s)
    return result


# ---------- endpoints --------------------------------------------------------


@app.post("/api/run/{pub}")
async def start_run(pub: str, background: BackgroundTasks):
    # 同步做严格格式校验：调用 normalize_publication_no 让 web 入口与 CLI 完全
    # 等价（容忍小写 / "-" 分隔 / 完整 Google Patents URL，规范化后再校验
    # ^[A-Z]{2}\d{6,}[A-Z]?\d?$）。失败直接 400，避免：
    #   1) 错号被 BackgroundTask 静默启动 → 前端误以为 {"started": true}
    #   2) data/output/<pub>/ + logs/<pub>/ 产生无意义的孤儿目录
    try:
        pub = normalize_publication_no(pub)
    except PatentFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _publication_root(pub)  # path-traversal 双保险（normalize 已经只返回字母数字）
    # 原子地占住 run 槽位：try_begin_run 直接 acquire 锁。失败说明已在跑 → 409。
    # 不能用「先 is_run_in_progress 检查、再排后台任务」两步——非原子，两个并发
    # 请求会都通过检查、都返回 started，其中一个随后在后台静默失败。
    token = try_begin_run(pub)
    if token is None:
        raise HTTPException(
            status_code=409,
            detail=f"pipeline for {pub} is already running",
        )
    # 已用 try_begin_run 同步占住槽位并拿到 token；后台按 token 跑完并释放，
    # 保证只有这次预留的持有者能释放该槽位。
    background.add_task(run_and_release, pub, token)
    return {"started": True, "publication_no": pub}


@app.get("/api/status/{pub}")
async def get_status(pub: str):
    summary = _module_output_summary(pub)
    modules = _module_status(pub)
    # merge summary into per-module dict
    for m in modules:
        m["summary"] = summary.get(m["id"], {})

    # pipeline-level state derived from run.jsonl
    events = list(iter_run_events(pub))
    pipeline_state = "idle"
    for ev in events:
        if ev.get("event") == "pipeline_start":
            pipeline_state = "running"
        elif ev.get("event") == "pipeline_end":
            pipeline_state = ev.get("status", "ok")

    return {"publication_no": pub, "pipeline_state": pipeline_state, "modules": modules}


@app.get("/api/log/{pub}/{module}")
async def get_log(pub: str, module: int, tail: int = 200):
    _publication_root(pub)
    if module not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="module must be 1..4")
    log_path = LOGS_ROOT / pub / f"module_{module}.log"
    if not log_path.exists():
        return JSONResponse({"lines": []})
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return {"lines": lines[-max(1, tail):]}


@app.get("/api/output/{pub}/{filename:path}")
async def get_output_file(pub: str, filename: str):
    root = _publication_root(pub)
    target = _safe_resolve(root, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target)


_REPORT_CSS = """
body { font-family: "PingFang SC", "Helvetica Neue", "Inter", "Arial", sans-serif;
       max-width: 980px; margin: 32px auto; padding: 0 24px 64px;
       font-size: 14.5px; line-height: 1.65; color: #1f1e1c; background: #faf7f2; }
h1 { font-size: 24pt; border-bottom: 2px solid #333; padding-bottom: 8pt; }
h2 { font-size: 17pt; margin-top: 26pt; border-bottom: 1px solid #ccc; padding-bottom: 4pt; }
h3 { font-size: 14pt; color: #444; margin-top: 20pt; }
h4, h5 { font-size: 12.5pt; color: #555; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; table-layout: fixed; }
th, td { border: 1px solid #888; padding: 6pt 8pt; font-size: 11pt;
         vertical-align: top; word-break: normal; overflow-wrap: anywhere; }
th { background: #f0e6d8; }
a { color: #c46446; text-decoration: none; word-break: break-all; }
a:hover { text-decoration: underline; }
blockquote { border-left: 3px solid #d97757; padding: 6pt 12pt; color: #555;
             background: #fdf9f3; margin: 8pt 0; border-radius: 0 4px 4px 0; }
code { background: #f3ede4; padding: 1px 5px; border-radius: 3px;
       font-family: "Menlo", "Courier New", monospace; font-size: 12pt; }
pre code { display: block; padding: 10pt; background: #1f1e1c; color: #e8e2d8; }
ul, ol { padding-left: 24px; }
"""


@app.get("/api/render/{pub}/{filename:path}")
async def render_markdown(pub: str, filename: str):
    """Render a .md file to a standalone HTML page so the browser shows it
    nicely rather than as raw markdown source."""
    root = _publication_root(pub)
    target = _safe_resolve(root, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if not target.name.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="only .md files can be rendered")

    try:
        import markdown as md_lib
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"markdown library not installed: {exc}",
        ) from exc

    import html as _html

    import nh3

    md_text = target.read_text(encoding="utf-8")
    # report.md 是 LLM 生成的，可能夹带原始 HTML（含 <script>）。markdown 默认
    # 放行原始 HTML，直接嵌进同源 HTMLResponse 就是存储型 XSS。渲染后用 nh3
    # 按白名单消毒，剥掉 script/onclick 等危险标签与属性。
    html_body = nh3.clean(md_lib.markdown(md_text, extensions=["tables", "fenced_code"]))
    page = (
        "<!doctype html><html lang='zh-CN'><head>"
        "<meta charset='utf-8'>"
        f"<title>{_html.escape(filename)} · {_html.escape(pub)}</title>"
        f"<style>{_REPORT_CSS}</style></head>"
        f"<body>{html_body}</body></html>"
    )
    from fastapi.responses import HTMLResponse
    return HTMLResponse(page)


@app.get("/api/runs")
async def list_runs():
    """List all publication_no directories that have run logs."""
    if not LOGS_ROOT.exists():
        return {"runs": []}
    runs = []
    for child in sorted(LOGS_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if child.is_dir():
            runs.append(child.name)
    return {"runs": runs}


def _build_historical_events(pub: str) -> list[dict]:
    """Merge run.jsonl + module_N.stream.jsonl + module_N.log into a single
    chronologically sorted list of SSE-shaped events.

    Sources:
      - run.jsonl                 → {"type":"progress", ...}  (ts inline)
      - module_N.stream.jsonl     → {"type":"token", ...}     (ts inline)
      - module_N.log              → {"type":"stdout", ...}    (no ts; we
                                     interpolate across the module's window)
    """
    pub_log_dir = LOGS_ROOT / pub
    if not pub_log_dir.exists():
        return []

    events: list[dict] = []

    module_windows: dict[int, dict] = {}
    for ev in iter_run_events(pub):
        ev_type = ev.get("event")
        n = ev.get("module")
        if ev_type == "start" and n is not None:
            module_windows.setdefault(n, {})["start"] = ev.get("ts")
        elif ev_type in ("done", "error") and n is not None:
            module_windows.setdefault(n, {})["end"] = ev.get("ts")
        events.append({"type": "progress", **ev})

    for n in (1, 2, 3, 4):
        stream_path = pub_log_dir / f"module_{n}.stream.jsonl"
        if not stream_path.exists():
            continue
        try:
            with stream_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("ts")
                    if ts is None:
                        continue
                    events.append({
                        "type": "token",
                        "module": n,
                        "ts": ts,
                        "delta": rec.get("delta", ""),
                    })
        except OSError:
            pass

    for n in (1, 2, 3, 4):
        log_path = pub_log_dir / f"module_{n}.log"
        if not log_path.exists():
            continue
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        lines = [ln for ln in lines if ln]
        if not lines:
            continue
        win = module_windows.get(n, {})
        t0 = win.get("start")
        t1 = win.get("end")
        if t0 is None or t1 is None or t1 <= t0:
            base = t0 if t0 is not None else 0.0
            for i, ln in enumerate(lines):
                events.append({
                    "type": "stdout",
                    "module": n,
                    "ts": base + i * 0.05,
                    "line": ln,
                })
        else:
            span = t1 - t0
            denom = max(1, len(lines) - 1) if len(lines) > 1 else 1
            for i, ln in enumerate(lines):
                ts = t0 + (i / denom) * span if len(lines) > 1 else t0
                events.append({
                    "type": "stdout",
                    "module": n,
                    "ts": ts,
                    "line": ln,
                })

    type_order = {"progress": 0, "stdout": 1, "token": 2}
    events.sort(key=lambda e: (e.get("ts") or 0, type_order.get(e.get("type"), 3)))
    return events


@app.get("/api/replay/{pub}")
async def get_replay(pub: str):
    pub_log_dir = LOGS_ROOT / pub
    if not pub_log_dir.exists():
        raise HTTPException(status_code=404, detail="run not found")

    events = _build_historical_events(pub)
    duration = 0.0
    if events:
        first = events[0].get("ts") or 0
        last = events[-1].get("ts") or 0
        if first and last:
            duration = max(0.0, last - first)

    return {
        "publication_no": pub,
        "duration_s": round(duration, 2),
        "event_count": len(events),
        "events": events,
    }


def _collect_export_outputs(pub: str) -> list[dict]:
    """Read the user-facing artifacts (those listed in module summaries) and
    return them as embeddable dicts:
      - kind="json" → {"content": "<raw text>"}
      - kind="md"   → {"html": "<rendered body html>"}
      - kind="pdf"  → {"base64": "<base64-encoded bytes>"}
    """
    import base64 as _b64

    try:
        root = _publication_root(pub)
    except HTTPException:
        return []

    summary = _module_output_summary(pub)
    outputs: list[dict] = []

    md_lib = None
    for module_id in sorted(summary):
        for f in summary[module_id].get("files") or []:
            name = f.get("name")
            kind = f.get("kind")
            if not name or not kind:
                continue
            try:
                target = _safe_resolve(root, name)
            except HTTPException:
                continue
            if not target.is_file():
                continue

            entry = {"module": module_id, "name": name, "kind": kind}
            try:
                if kind == "json":
                    entry["content"] = target.read_text(encoding="utf-8")
                elif kind == "md":
                    if md_lib is None:
                        try:
                            import markdown as md_lib
                        except ImportError:
                            md_lib = False
                    md_text = target.read_text(encoding="utf-8")
                    if md_lib:
                        import nh3

                        # 导出的回放离线 HTML 会把这段 html 直接插进 Blob 页面，
                        # LLM markdown 里的原始 <script> 会原样执行 → 存储型 XSS。
                        # 与 /api/render 一致用 nh3 消毒后再写出。
                        entry["html"] = nh3.clean(
                            md_lib.markdown(
                                md_text, extensions=["tables", "fenced_code"]
                            )
                        )
                    else:
                        # markdown lib missing — fall back to raw text wrapped in <pre>
                        from html import escape as _esc
                        entry["html"] = f"<pre>{_esc(md_text)}</pre>"
                elif kind == "pdf":
                    entry["base64"] = _b64.b64encode(target.read_bytes()).decode("ascii")
                else:
                    entry["content"] = target.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            outputs.append(entry)

    return outputs


@app.get("/api/replay/{pub}/export")
async def export_replay(pub: str):
    """Export a standalone HTML replay file that runs without the server.

    All events + CSS + JS are inlined; opening the file in any browser will
    show the same replay UI (play/pause + 1x/20x/100x/600x speeds + scrub bar).
    """
    pub_log_dir = LOGS_ROOT / pub
    if not pub_log_dir.exists():
        raise HTTPException(status_code=404, detail="run not found")

    template_path = WEB_DIR / "replay_export.html"
    styles_path = WEB_DIR / "styles.css"
    if not template_path.exists() or not styles_path.exists():
        raise HTTPException(status_code=500, detail="export template missing")

    events = _build_historical_events(pub)
    duration = 0.0
    if events:
        first = events[0].get("ts") or 0
        last = events[-1].get("ts") or 0
        if first and last:
            duration = max(0.0, last - first)

    outputs = _collect_export_outputs(pub)

    payload = {
        "publication_no": pub,
        "duration_s": round(duration, 2),
        "event_count": len(events),
        "events": events,
        "outputs": outputs,
        "report_css": _REPORT_CSS,
    }

    # Embedded inside <script type="application/json">; only "</" needs escaping
    # so the browser doesn't terminate the script element early.
    events_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    styles_text = styles_path.read_text(encoding="utf-8")

    html = (
        template_path.read_text(encoding="utf-8")
        .replace("__STYLES__", styles_text)
        .replace("__PUB__", pub)
        .replace("__EVENTS_JSON__", events_json)
    )

    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        html,
        headers={
            "Content-Disposition": f'attachment; filename="patentradar_replay_{pub}.html"',
        },
    )


# ---------- SSE: live stream -------------------------------------------------


async def _sse_event_stream(pub: str, request: Request | None = None) -> AsyncIterator[str]:
    """Continuously tail run.jsonl + per-module stream.jsonl + module_N.log,
    push SSE events.

    Push types:
      - {"type":"status", "modules": [...]}                            (initial)
      - {"type":"progress", "event":..., "module":..., ...}            (lifecycle)
      - {"type":"token",  "module": N, "delta": "..."}                 (LLM delta)
      - {"type":"stdout", "module": N, "line":  "..."}                 (cli stdout)

    Initial-connect behavior: dump all historical events sorted by ts so the
    client sees them in true chronological order (lifecycle + token + stdout
    interleaved). Then jump file offsets to current EOF and enter the live
    tail loop.
    """
    pub_log_dir = LOGS_ROOT / pub
    run_log = pub_log_dir / "run.jsonl"
    stream_logs = {n: pub_log_dir / f"module_{n}.stream.jsonl" for n in (1, 2, 3, 4)}
    stdout_logs = {n: pub_log_dir / f"module_{n}.log" for n in (1, 2, 3, 4)}

    # 1) Initial status snapshot.
    snapshot = {
        "type": "status",
        "modules": _module_status(pub),
    }
    yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

    # 2) Dump merged historical events in chronological order.
    historical = _build_historical_events(pub)
    for ev in historical:
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    # 3) Jump file offsets to current EOF so live tail picks up new content only.
    def _file_size(p: Path) -> int:
        try:
            return p.stat().st_size if p.exists() else 0
        except OSError:
            return 0

    run_offset = _file_size(run_log)
    stream_offsets: dict[int, int] = {n: _file_size(stream_logs[n]) for n in (1, 2, 3, 4)}
    stdout_offsets: dict[int, int] = {n: _file_size(stdout_logs[n]) for n in (1, 2, 3, 4)}

    pipeline_ended = False
    # pipeline_end 后再额外 tail 几轮，保证最后一批 token / stdout 行被吐出去
    trailing_rounds_after_end = 0

    while True:
        # 客户端断连 → 主动退出循环，否则每个关闭的 tab 都留一个常驻协程
        if request is not None and await request.is_disconnected():
            return

        # Tail run.jsonl (lifecycle events)
        if run_log.exists():
            try:
                with run_log.open("r", encoding="utf-8") as f:
                    f.seek(run_offset)
                    new_data = f.read()
                    run_offset = f.tell()
                for line in new_data.splitlines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = {"type": "progress", **ev}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    if ev.get("event") == "pipeline_end":
                        final_status = {"type": "status", "modules": _module_status(pub)}
                        yield f"data: {json.dumps(final_status, ensure_ascii=False)}\n\n"
                        pipeline_ended = True
            except OSError:
                pass

        # Tail every module's stream.jsonl (LLM token deltas)
        for n, path in stream_logs.items():
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    f.seek(stream_offsets[n])
                    new_data = f.read()
                    stream_offsets[n] = f.tell()
                for line in new_data.splitlines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = {
                        "type": "token",
                        "module": n,
                        "ts": ev.get("ts"),
                        "delta": ev.get("delta", ""),
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except OSError:
                pass

        # Tail every module's plain stdout log
        for n, path in stdout_logs.items():
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(stdout_offsets[n])
                    new_data = f.read()
                    stdout_offsets[n] = f.tell()
                if not new_data:
                    continue
                for line in new_data.splitlines():
                    if not line:
                        continue
                    payload = {
                        "type": "stdout",
                        "module": n,
                        "ts": time.time(),  # 实时到达时间，方便前端显示
                        "line": line,
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except OSError:
                pass

        # pipeline 已结束 → 再吐若干轮把残留的 token / stdout 收尾，然后退出
        if pipeline_ended:
            trailing_rounds_after_end += 1
            if trailing_rounds_after_end >= _SSE_TRAILING_ROUNDS_AFTER_END:
                return

        await asyncio.sleep(0.4)


@app.get("/api/stream/{pub}")
async def sse_stream(pub: str, request: Request):
    _publication_root(pub)
    return StreamingResponse(
        _sse_event_stream(pub, request=request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- static frontend --------------------------------------------------

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
