"""Payload 压缩工具：当 worker 构造的 user_text 字符数逼近 codex 上限时，
按优先级低 → 高的顺序逐档压缩低价值字段，保证一次 LLM 调用不会因 prompt 超限失败。

使用约定：worker 把 payload(dict) 构造完后调 `compress_payload_if_needed`，
该函数会就地修改 payload 并返回字符数缩到目标阈值以下。

压缩档位（由低到高 invasiveness）：
  1. fetched_pages.text 4000 → 2500 字符
  2. fetched_pages.text 2500 → 1500 字符
  3. search_results.snippet 600 → 300 字符
  4. fetched_pages 数量上限 → 留前 10 条
  5. search_results 数量上限 → 留前 20 条
  6. images_manifest 全删（兜底；图实际还会通过 vision 通道送）

每档压完后重新评估字符数，达标就停。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from patentradar.core.constants import COMPRESS_TARGET_CHARS

logger = logging.getLogger(__name__)

# COMPRESS_TARGET_CHARS 从 core.constants 派生（由 PATENTRADAR_CONTEXT_LENGTH env 派生，
# 默认是 PROMPT_SIZE_CRITICAL_CHARS × 80%，给 system prompt 留余量）。
# Re-export 给老代码用：


def compress_payload_if_needed(
    payload: dict[str, Any],
    *,
    target_chars: int = COMPRESS_TARGET_CHARS,
    context_label: str = "",
) -> dict[str, Any]:
    """就地压缩 payload 直到 dump 后字符数 ≤ target_chars。

    操作的字段路径（兼容模块二/三两套 payload 结构）：
    - 模块二: payload["candidates"][i]["fetched_pages"|"search_results"|"fetched_page_images"]
    - 模块三: payload["module_two_evidence"]["evidence_pool"|"images_manifest"]
              + payload["new_search_results"]
    """
    def _size() -> int:
        return len(json.dumps(payload, ensure_ascii=False))

    initial = _size()
    if initial <= target_chars:
        return payload

    # 档 1: fetched_pages.text 限到 2500
    _truncate_pages_text(payload, max_chars=2500)
    if _size() <= target_chars:
        _log_done(initial, _size(), 1, context_label)
        return payload

    # 档 2: fetched_pages.text 限到 1500
    _truncate_pages_text(payload, max_chars=1500)
    if _size() <= target_chars:
        _log_done(initial, _size(), 2, context_label)
        return payload

    # 档 3: search_results snippet 限到 300
    _truncate_search_snippet(payload, max_chars=300)
    if _size() <= target_chars:
        _log_done(initial, _size(), 3, context_label)
        return payload

    # 档 4: fetched_pages 只留前 10
    _cap_pages(payload, max_count=10)
    if _size() <= target_chars:
        _log_done(initial, _size(), 4, context_label)
        return payload

    # 档 5: search_results 只留前 20
    _cap_search_results(payload, max_count=20)
    if _size() <= target_chars:
        _log_done(initial, _size(), 5, context_label)
        return payload

    # 档 6: 删 images_manifest（图本身仍通过 vision 通道送，manifest 只是引用辅助）
    _drop_images_manifest(payload)
    final = _size()
    if final <= target_chars:
        _log_done(initial, final, 6, context_label)
        return payload

    # 全压完仍超标 → 仅 warn 不再砍，让 codex.py 的 _check_prompt_size 兜底 raise
    logger.warning(
        "payload compress %s: all 6 levels applied but still %s > target %s",
        context_label or "?", f"{final:,}", f"{target_chars:,}",
    )
    return payload


def _log_done(before: int, after: int, level: int, label: str) -> None:
    logger.warning(
        "payload compress %s: %s → %s chars at level %d",
        label or "?", f"{before:,}", f"{after:,}", level,
    )


def _iter_candidates(payload: dict) -> list[dict]:
    """统一拿到所有可能含 fetched_pages / search_results 的子字典。"""
    out: list[dict] = []
    for c in payload.get("candidates") or []:
        out.append(c)
    return out


def _truncate_pages_text(payload: dict, *, max_chars: int) -> None:
    # 模块二 candidates[].fetched_pages[].text
    for c in _iter_candidates(payload):
        for p in c.get("fetched_pages") or []:
            text = p.get("text") or ""
            if len(text) > max_chars:
                p["text"] = text[:max_chars]
    # 模块三 module_two_evidence.evidence_pool[].text
    pool = (payload.get("module_two_evidence") or {}).get("evidence_pool") or []
    for p in pool:
        text = p.get("text") or ""
        if len(text) > max_chars:
            p["text"] = text[:max_chars]


def _truncate_search_snippet(payload: dict, *, max_chars: int) -> None:
    for c in _iter_candidates(payload):
        for r in c.get("search_results") or []:
            snippet = r.get("snippet") or ""
            if len(snippet) > max_chars:
                r["snippet"] = snippet[:max_chars]
    for r in payload.get("new_search_results") or []:
        snippet = r.get("snippet") or ""
        if len(snippet) > max_chars:
            r["snippet"] = snippet[:max_chars]
    # 顶层 search_results（candidate_worker 的 payload 结构：在 payload 顶层而非 candidates[i] 内）
    for r in payload.get("search_results") or []:
        snippet = r.get("snippet") or ""
        if len(snippet) > max_chars:
            r["snippet"] = snippet[:max_chars]


def _cap_pages(payload: dict, *, max_count: int) -> None:
    for c in _iter_candidates(payload):
        pages = c.get("fetched_pages")
        if pages and len(pages) > max_count:
            c["fetched_pages"] = pages[:max_count]
    m2 = payload.get("module_two_evidence") or {}
    pool = m2.get("evidence_pool")
    if pool and len(pool) > max_count:
        m2["evidence_pool"] = pool[:max_count]


def _cap_search_results(payload: dict, *, max_count: int) -> None:
    for c in _iter_candidates(payload):
        results = c.get("search_results")
        if results and len(results) > max_count:
            c["search_results"] = results[:max_count]
    results = payload.get("new_search_results")
    if results and len(results) > max_count:
        payload["new_search_results"] = results[:max_count]
    # 顶层 search_results（candidate_worker 的 payload 结构）
    results = payload.get("search_results")
    if results and len(results) > max_count:
        payload["search_results"] = results[:max_count]


def _drop_images_manifest(payload: dict) -> None:
    for c in _iter_candidates(payload):
        c.pop("fetched_page_images", None)
    m2 = payload.get("module_two_evidence")
    if m2:
        m2.pop("images_manifest", None)
