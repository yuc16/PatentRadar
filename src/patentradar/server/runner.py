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
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]  # PatentRadar/
DATA_OUTPUT = ROOT / "data" / "output"
LOGS_ROOT = ROOT / "logs"

# 流水线产物的格式版本。bump 即让"整条流水线已完成"的旧 run 失效（见
# _is_fully_cached）——否则证据白名单等修复对已经跑完的专利无效，Web 重跑会
# 继续复用旧的高分伪造报告。
PIPELINE_VERSION = 2

# 正在运行的 pub → 不可伪造的 reservation token，整体由 _locks_guard 保护。
# 用 token 而非单纯 set / per-pub Lock：
#   - set + discard：任何人调 release(pub) 都能清掉别人的预留（无所有权）。
#   - per-pub Lock + locked() 自省：存在 ABA 竞态，两线程可各拿不同 Lock 都成功。
# 现在只有持有当初 try_begin_run 返回的 token 的人才能释放对应槽位，占位/释放/
# 查询全在同一把 guard 内原子完成。
_in_progress: dict[str, str] = {}
_locks_guard = Lock()


def is_run_in_progress(pub: str) -> bool:
    """非阻塞探测某 pub 的 pipeline 是否正在跑。"""
    with _locks_guard:
        return pub in _in_progress


def try_begin_run(pub: str) -> str | None:
    """原子地占住某 pub 的 run 槽位。成功返回一个 reservation token（调用方此后
    必须用该 token 调 run_and_release 释放），已在跑返回 None。检查与占位在同一把
    guard 内完成，杜绝两个并发请求都返回 started。"""
    with _locks_guard:
        if pub in _in_progress:
            return None
        token = uuid.uuid4().hex
        _in_progress[pub] = token
        return token


def _end_run(pub: str, token: str) -> None:
    """释放某 pub 的 run 槽位——仅当 token 与当前预留持有者一致。这样一个没有
    持有预留的误调用无法清掉正在运行的 run 状态。"""
    with _locks_guard:
        if _in_progress.get(pub) == token:
            del _in_progress[pub]


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


def _tail_message(log_path: Path, *, max_lines: int = 6, max_chars: int = 500) -> str:
    # subprocess 失败时只暴露 exit_code,前端只看到 "exit_code=1" 不知所云。
    # 从 module_N.log 末尾捞最后几行非空内容当作人话错误消息,
    # 让 Google Patents 503 / 429 这类暂时性故障能透到 UI。
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    tail = [ln.strip() for ln in lines[-max_lines:] if ln.strip()]
    msg = " | ".join(tail)
    return msg[-max_chars:] if len(msg) > max_chars else msg


def _env_for_step(step: ModuleStep, stream_log: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATENTRADAR_STREAM_LOG"] = str(stream_log)
    env["PATENTRADAR_MODULE_LABEL"] = f"module_{step.n}"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_pipeline(pub: str) -> None:
    """Standalone entrypoint (CLI / direct callers): atomically reserve the run
    slot, run, release. Raises if a run for `pub` is already in progress — never
    runs concurrently and never releases a slot it didn't own.

    The FastAPI layer does NOT use this; it reserves via try_begin_run() (for the
    synchronous 409) and then schedules run_and_release()."""
    token = try_begin_run(pub)
    if token is None:
        raise RuntimeError(f"pipeline for {pub} is already running")
    run_and_release(pub, token)


def run_and_release(pub: str, token: str) -> None:
    """Run the pipeline for a slot reserved via try_begin_run(), then release it
    using the reservation token.

    Verifies ownership BEFORE running: a stale/erroneous background task whose
    token no longer matches the current reservation must not execute the
    pipeline at all (otherwise it would concurrently write the same logs /
    artifacts as the real holder). Only the current holder runs and releases."""
    with _locks_guard:
        if _in_progress.get(pub) != token:
            return
    try:
        _run_pipeline_locked(pub)
    finally:
        _end_run(pub, token)


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
    # 旧版本（或无版本标记）的完成 run 不可复用——否则证据白名单 / 失格修复对
    # 已跑完的专利永远不生效，Web 重跑会继续拿旧的伪造高分报告。
    if last_pipeline_end.get("pipeline_version") != PIPELINE_VERSION:
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
                        "message": _tail_message(step_log),
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
            "pipeline_version": PIPELINE_VERSION,
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
