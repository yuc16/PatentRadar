"""Process-wide LLM token-stream callback registry.

Pipelines / CLI set the callback once at startup (via env var or directly);
provider implementations call `emit_delta()` for every SSE delta they read.
The callback is responsible for persisting the delta (e.g. to a log file).

We use contextvars so that, in a future world with concurrent runs, each task
can have its own callback without leaking across.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

OnDelta = Callable[[str], None]

_on_delta: contextvars.ContextVar[OnDelta | None] = contextvars.ContextVar(
    "patentradar_llm_on_delta", default=None
)
_module_label: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "patentradar_llm_module_label", default=None
)


def set_on_delta(cb: OnDelta | None) -> None:
    _on_delta.set(cb)


def set_module_label(label: str | None) -> None:
    """Tag every subsequent emit_delta() with a module label (e.g. 'module_2')."""
    _module_label.set(label)


def emit_delta(text: str) -> None:
    if not text:
        return
    cb = _on_delta.get()
    if cb is None:
        return
    try:
        cb(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("on_delta callback raised: %s", exc)


def install_file_writer_from_env() -> None:
    """If PATENTRADAR_STREAM_LOG is set, register a JSONL file writer as on_delta.

    Each delta is written as one line: {"ts":..., "module":..., "delta": "..."}.
    """
    path = os.environ.get("PATENTRADAR_STREAM_LOG")
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fh = target.open("a", encoding="utf-8", buffering=1)  # line-buffered

    import time

    def _write(delta: str) -> None:
        record = {
            "ts": time.time(),
            "module": _module_label.get(),
            "delta": delta,
        }
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    set_on_delta(_write)
