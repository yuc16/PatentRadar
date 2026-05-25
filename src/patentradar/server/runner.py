"""Run the 4-module PatentRadar pipeline as a chain of CLI subprocesses.

Lives outside the request/response cycle. The FastAPI layer fires off a
background task that calls `run_pipeline(publication_no)`; everything else is
file-based (logs/, data/output/), which the web UI polls via SSE + REST.

Each module's stdout/stderr is tee'd to `logs/<publication_no>/module_<N>.log`.
The runner also appends one JSONL line per lifecycle event to
`logs/<publication_no>/run.jsonl`:

    {"ts": ..., "module": 1, "event": "start"}
    {"ts": ..., "module": 1, "event": "done", "elapsed": 23.4}
    {"ts": ..., "module": 2, "event": "error", "elapsed": 5.1, "message": "..."}

LLM token deltas are written by the CLI itself (via
patentradar.llm.stream.install_file_writer_from_env) when we pass
`PATENTRADAR_STREAM_LOG=logs/<pub>/module_<N>.stream.jsonl` in the env.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]  # PatentRadar/
DATA_OUTPUT = ROOT / "data" / "output"
LOGS_ROOT = ROOT / "logs"

_run_locks: dict[str, Lock] = {}
_locks_guard = Lock()


def _lock_for(pub: str) -> Lock:
    with _locks_guard:
        if pub not in _run_locks:
            _run_locks[pub] = Lock()
        return _run_locks[pub]


def is_run_in_progress(pub: str) -> bool:
    """非阻塞探测某 pub 的 pipeline 是否正在跑。用于 FastAPI 同步返回 409。"""
    with _locks_guard:
        lock = _run_locks.get(pub)
    if lock is None:
        return False
    return lock.locked()


def _release_lock_entry(pub: str) -> None:
    """跑完后丢弃 _run_locks 里该 pub 的条目，避免长跑服务端字典无界增长。
    只在锁当前未被占用时弹出（防止误删一个还在跑的并发 run 的锁实例）。"""
    with _locks_guard:
        existing = _run_locks.get(pub)
        if existing is not None and not existing.locked():
            _run_locks.pop(pub, None)


@dataclass
class ModuleStep:
    n: int
    label: str
    cli_args: list[str]


def _build_steps(pub: str) -> list[ModuleStep]:
    out_dir = DATA_OUTPUT / pub
    tp_path = out_dir / "task_package.json"
    top_path = out_dir / "step5_top5_claim1_candidates.json"
    chart_path = out_dir / "top5_full_claim_chart.json"
    return [
        ModuleStep(
            n=1,
            label="decompose",
            cli_args=["decompose", pub, "--output-dir", str(DATA_OUTPUT)],
        ),
        ModuleStep(
            n=2,
            label="competitor-search",
            cli_args=["competitor-search", str(tp_path), "--output-dir", str(out_dir)],
        ),
        ModuleStep(
            n=3,
            label="full-claim-chart",
            cli_args=[
                "full-claim-chart",
                str(tp_path),
                str(top_path),
                "--output-dir",
                str(out_dir),
            ],
        ),
        ModuleStep(
            n=4,
            label="report",
            cli_args=[
                "report",
                str(tp_path),
                str(chart_path),
                "--output-dir",
                str(out_dir),
            ],
        ),
    ]


def _append_event(run_log: Path, event: dict) -> None:
    run_log.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": time.time(), **event}
    with run_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _env_for_step(step: ModuleStep, stream_log: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATENTRADAR_STREAM_LOG"] = str(stream_log)
    env["PATENTRADAR_MODULE_LABEL"] = f"module_{step.n}"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_pipeline(pub: str) -> None:
    """Run the full 4-module pipeline for one publication. Blocking."""
    lock = _lock_for(pub)
    if not lock.acquire(blocking=False):
        raise RuntimeError(f"pipeline for {pub} is already running")
    try:
        _run_pipeline_locked(pub)
    finally:
        lock.release()
        _release_lock_entry(pub)


def _is_fully_cached(pub: str) -> bool:
    """A prior run is considered fully cached and reusable when:
      1) logs/<pub>/run.jsonl ends with pipeline_end status=ok, AND
      2) all four modules' final artifacts are present on disk.
    In that case we skip the pipeline entirely, keeping run.jsonl + module logs
    intact so the dashboard / replay export keep working against the old run.
    """
    pub_log_dir = LOGS_ROOT / pub
    run_log = pub_log_dir / "run.jsonl"
    if not run_log.exists():
        return False

    last_pipeline_end = None
    for ev in iter_run_events(pub):
        if ev.get("event") == "pipeline_end":
            last_pipeline_end = ev
    if not last_pipeline_end or last_pipeline_end.get("status") != "ok":
        return False

    out = DATA_OUTPUT / pub
    required = (
        "task_package.json",                  # module 1
        "step5_top5_claim1_candidates.json",  # module 2
        "top5_full_claim_chart.json",         # module 3
        "report.md",                          # module 4
    )
    return all((out / name).is_file() for name in required)


def _run_pipeline_locked(pub: str) -> None:
    pub_log_dir = LOGS_ROOT / pub
    pub_log_dir.mkdir(parents=True, exist_ok=True)
    run_log = pub_log_dir / "run.jsonl"

    # Fully-cached short-circuit: previous successful run with all artifacts
    # on disk → reuse everything, don't touch run.jsonl / module logs / outputs.
    if _is_fully_cached(pub):
        return

    # Truncate previous run.jsonl so the dashboard reflects only this run.
    run_log.write_text("", encoding="utf-8")

    _append_event(run_log, {"event": "pipeline_start", "publication_no": pub})

    steps = _build_steps(pub)
    pipeline_started = time.time()

    for step in steps:
        step_log = pub_log_dir / f"module_{step.n}.log"
        stream_log = pub_log_dir / f"module_{step.n}.stream.jsonl"
        # Truncate per-step logs at start so the UI always sees a clean run.
        step_log.write_text("", encoding="utf-8")
        stream_log.write_text("", encoding="utf-8")

        _append_event(
            run_log,
            {"module": step.n, "label": step.label, "event": "start"},
        )
        started = time.time()
        cmd = [sys.executable, "-m", "patentradar.cli", *step.cli_args]

        try:
            with step_log.open("a", encoding="utf-8") as logf:
                logf.write(f"$ {' '.join(shlex.quote(c) for c in cmd)}\n")
                logf.flush()
                process = subprocess.Popen(
                    cmd,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    env=_env_for_step(step, stream_log),
                    cwd=str(ROOT),
                )
                rc = process.wait()
            elapsed = time.time() - started
            if rc != 0:
                _append_event(
                    run_log,
                    {
                        "module": step.n,
                        "label": step.label,
                        "event": "error",
                        "elapsed": round(elapsed, 2),
                        "exit_code": rc,
                        "log_path": str(step_log.relative_to(ROOT)),
                    },
                )
                _append_event(
                    run_log,
                    {
                        "event": "pipeline_end",
                        "status": "failed",
                        "failed_at_module": step.n,
                        "elapsed": round(time.time() - pipeline_started, 2),
                    },
                )
                return
            _append_event(
                run_log,
                {
                    "module": step.n,
                    "label": step.label,
                    "event": "done",
                    "elapsed": round(elapsed, 2),
                    "log_path": str(step_log.relative_to(ROOT)),
                },
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - started
            _append_event(
                run_log,
                {
                    "module": step.n,
                    "label": step.label,
                    "event": "error",
                    "elapsed": round(elapsed, 2),
                    "message": str(exc)[:500],
                },
            )
            _append_event(
                run_log,
                {
                    "event": "pipeline_end",
                    "status": "failed",
                    "failed_at_module": step.n,
                    "elapsed": round(time.time() - pipeline_started, 2),
                },
            )
            return

    _append_event(
        run_log,
        {
            "event": "pipeline_end",
            "status": "ok",
            "elapsed": round(time.time() - pipeline_started, 2),
        },
    )


def iter_run_events(pub: str) -> Iterable[dict]:
    """Yield every JSONL event currently in run.jsonl (no tailing)."""
    run_log = LOGS_ROOT / pub / "run.jsonl"
    if not run_log.exists():
        return
    with run_log.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
