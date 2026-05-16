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
import os
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from patentradar.server.runner import (
    DATA_OUTPUT,
    LOGS_ROOT,
    ROOT,
    iter_run_events,
    run_pipeline,
)

# Load .env from project root so subprocess env inherits API keys etc.
load_dotenv(ROOT / ".env")

app = FastAPI(title="PatentRadar Dashboard")

WEB_DIR = ROOT / "web"


# ---------- helpers ----------------------------------------------------------


def _publication_root(pub: str) -> Path:
    # Mild sanity guard against path traversal — publication numbers are
    # always alphanumeric (e.g. CN114512759B).
    if not pub or not pub.replace("/", "").replace("\\", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid publication_no")
    return DATA_OUTPUT / pub


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
            }
        except Exception:  # noqa: BLE001
            summary[3] = {"error": "full_claim_chart unparseable"}

    report_md = root / "report.md"
    report_pdf = root / "report.pdf"
    if report_md.exists():
        summary[4] = {
            "report_md": str(report_md.relative_to(ROOT)),
            "report_pdf": str(report_pdf.relative_to(ROOT)) if report_pdf.exists() else None,
            "size_bytes": report_md.stat().st_size,
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
    _publication_root(pub)  # validate format
    try:
        background.add_task(run_pipeline, pub)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    target = (root / filename).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target)


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


@app.get("/api/replay/{pub}")
async def get_replay(pub: str):
    """Return all events for one run, sorted by ts, ready for client-side replay.

    Sources merged:
      - run.jsonl                     (lifecycle, ts inline)
      - module_N.stream.jsonl         (LLM token, ts inline)
      - module_N.log                  (stdout, NO inline ts → linearly
                                       interpolated across the module's
                                       [start_ts, end_ts] interval)
    """
    pub_log_dir = LOGS_ROOT / pub
    if not pub_log_dir.exists():
        raise HTTPException(status_code=404, detail="run not found")

    events: list[dict] = []

    # Lifecycle from run.jsonl + figure out each module's time window
    module_windows: dict[int, dict] = {}  # n -> {"start": ts, "end": ts}
    for ev in iter_run_events(pub):
        ev_type = ev.get("event")
        n = ev.get("module")
        if ev_type == "start" and n is not None:
            module_windows.setdefault(n, {})["start"] = ev.get("ts")
        elif ev_type in ("done", "error") and n is not None:
            module_windows.setdefault(n, {})["end"] = ev.get("ts")
        events.append({"type": "progress", **ev})

    # LLM token deltas — ts already on each line.
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

    # stdout — no per-line ts, interpolate across the module's window.
    for n in (1, 2, 3, 4):
        log_path = pub_log_dir / f"module_{n}.log"
        if not log_path.exists():
            continue
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        # filter empty lines (we still want to preserve them in display, but
        # interpolation gets weird with thousands of blanks → drop them).
        lines = [ln for ln in lines if ln]
        if not lines:
            continue
        win = module_windows.get(n, {})
        t0 = win.get("start")
        t1 = win.get("end")
        if t0 is None or t1 is None or t1 <= t0:
            # Module is still running or window unknown → spread evenly across
            # whatever we have. Use the start (or 0) so events at least have a ts.
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

    # Sort merged stream by ts (stable). Ties: progress < stdout < token.
    type_order = {"progress": 0, "stdout": 1, "token": 2}
    events.sort(key=lambda e: (e.get("ts") or 0, type_order.get(e.get("type"), 3)))

    duration = 0.0
    if events:
        first = events[0]["ts"]
        last = events[-1]["ts"]
        if first and last:
            duration = max(0.0, last - first)

    return {
        "publication_no": pub,
        "duration_s": round(duration, 2),
        "event_count": len(events),
        "events": events,
    }


# ---------- SSE: live stream -------------------------------------------------


async def _sse_event_stream(pub: str) -> AsyncIterator[str]:
    """Continuously tail run.jsonl + per-module stream.jsonl + module_N.log,
    push SSE events.

    Push types:
      - {"type":"status", "modules": [...]}                            (initial)
      - {"type":"progress", "event":..., "module":..., ...}            (lifecycle)
      - {"type":"token",  "module": N, "delta": "..."}                 (LLM delta)
      - {"type":"stdout", "module": N, "line":  "..."}                 (cli stdout)
    """
    pub_log_dir = LOGS_ROOT / pub
    run_log = pub_log_dir / "run.jsonl"
    stream_logs = {n: pub_log_dir / f"module_{n}.stream.jsonl" for n in (1, 2, 3, 4)}
    stdout_logs = {n: pub_log_dir / f"module_{n}.log" for n in (1, 2, 3, 4)}

    # File offsets we've already streamed.
    run_offset = 0
    stream_offsets: dict[int, int] = {n: 0 for n in (1, 2, 3, 4)}
    stdout_offsets: dict[int, int] = {n: 0 for n in (1, 2, 3, 4)}

    # Initial snapshot.
    snapshot = {
        "type": "status",
        "modules": _module_status(pub),
    }
    yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

    while True:
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
                        "line": line,
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except OSError:
                pass

        await asyncio.sleep(0.4)


@app.get("/api/stream/{pub}")
async def sse_stream(pub: str):
    _publication_root(pub)
    return StreamingResponse(
        _sse_event_stream(pub),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- static frontend --------------------------------------------------

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
