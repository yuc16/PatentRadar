"""ChatGPT OAuth client for Codex Responses.

This follows the existing project approach: read ``~/.codex/auth.json`` and call
the ChatGPT backend Codex Responses SSE endpoint. It supports text and image
inputs for module-one PDF claim reconstruction.

`CodexProvider` is the LLMProvider-conformant wrapper used by the global
factory in `provider.py`. The module-level `chat` and `chat_json` functions are
kept as the backend implementation; callers should go through
`get_llm_provider()` rather than importing them directly.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
AUTH_PATH = Path.home() / ".codex" / "auth.json"
logger = logging.getLogger(__name__)

# Prompt-size 监控阈值由 core.constants 派生（基于 PATENTRADAR_CONTEXT_LENGTH env，
# 默认 258K tokens；换模型只改 env 即可）。
# warn: 给出预警，提示调用方应该自查/压缩
# critical: 接近上限，立即 raise，让 caller 端 catch 后压缩重试或降级
from patentradar.core.constants import (  # noqa: E402
    PROMPT_SIZE_CRITICAL_CHARS,
    PROMPT_SIZE_WARN_CHARS,
)


class PromptTooLargeError(RuntimeError):
    """Prompt 超出 codex 后端 context window 安全余量；caller 端应压缩 user_text 后重试。"""


class CodexAuthError(RuntimeError):
    pass


def chat(
    *,
    system: str,
    user_text: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    verbosity: str = "medium",
    response_format: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> str:
    model = model or DEFAULT_MODEL
    timeout = timeout or int(os.getenv("CODEX_STREAM_TIMEOUT", "900"))

    _check_prompt_size(system=system, user_text=user_text, model=model)

    user_content: list[dict[str, Any]] = [{"type": "input_text", "text": user_text}]
    for image in images or []:
        user_content.append({"type": "input_image", "image_url": _image_to_data_url(image)})

    text_options: dict[str, Any] = {"verbosity": verbosity}
    if response_format is not None:
        text_options["format"] = response_format

    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "stream": True,
        "instructions": system,
        "input": [{"role": "user", "content": user_content}],
        "text": text_options,
        "reasoning": {"effort": reasoning_effort, "summary": "auto"},
        "include": ["reasoning.encrypted_content"],
        "tool_choice": "none",
        "parallel_tool_calls": False,
    }

    timeout_obj = httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0)
    parts: list[str] = []
    with httpx.Client(timeout=timeout_obj) as client:
        with client.stream("POST", CODEX_URL, headers=_headers(), json=body) as response:
            if response.status_code != 200:
                raw = response.read().decode("utf-8", "ignore")
                raise RuntimeError(_friendly_error(response.status_code, raw))
            for event in _iter_sse(response):
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    delta = event.get("delta") or ""
                    if delta:
                        parts.append(delta)
                        from patentradar.llm.stream import emit_delta
                        emit_delta(delta)
                elif event_type in {"error", "response.failed"}:
                    raise RuntimeError(
                        f"Codex stream error: {json.dumps(event, ensure_ascii=False)[:500]}"
                    )
    return "".join(parts)


def chat_json(
    *,
    system: str,
    user_text: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    verbosity: str = "medium",
    response_format: dict[str, Any] | None = None,
    timeout: int | None = None,
    attempts: int = 3,
    retry_delay_seconds: float = 20.0,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            text = chat(
                system=system,
                user_text=user_text,
                images=images,
                model=model,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                response_format=response_format,
                timeout=timeout,
            )
            return _parse_json(text)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= attempts or not _is_retryable_error(exc):
                raise
            sleep_seconds = retry_delay_seconds * attempt
            logger.warning("Codex JSON retry %d/%d after error: %s", attempt, attempts, exc)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    raise RuntimeError(str(last_exc) if last_exc else "Codex JSON call failed")


def _headers() -> dict[str, str]:
    access_token, account_id = _load_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "OpenAI-Beta": "responses=experimental",
        "originator": os.getenv("OPENAI_CODEX_ORIGINATOR", "patent-radar"),
        "User-Agent": "patent-radar (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    return headers


def _load_token() -> tuple[str, str]:
    if not AUTH_PATH.exists():
        raise CodexAuthError(
            f"Missing {AUTH_PATH}. Run `codex login` with the official Codex CLI first."
        )
    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexAuthError(f"Failed to read {AUTH_PATH}: {exc}") from exc
    tokens = data.get("tokens") or {}
    access_token = tokens.get("access_token") or ""
    account_id = tokens.get("account_id") or ""
    if not access_token:
        raise CodexAuthError(f"No access_token in {AUTH_PATH}. Re-run `codex login`.")
    return access_token, account_id


def _image_to_data_url(image_bytes: bytes, mime: str = "image/png") -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _iter_sse(response: httpx.Response) -> Iterator[dict[str, Any]]:
    buffer: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if not buffer:
                continue
            payload_lines = [item[5:].strip() for item in buffer if item.startswith("data:")]
            buffer = []
            raw = "\n".join(payload_lines).strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue
            continue
        buffer.append(line)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _check_prompt_size(*, system: str, user_text: str, model: str) -> None:
    """监控 prompt 字符数，warn 临近上限、超阈值直接 raise PromptTooLargeError。

    raise 让 caller (worker) 在 except 里压缩 user_text 重试，而不是把
    超大请求发出去等 codex 后端返回 token-limit 错误（贵且慢）。
    """
    total_chars = len(system) + len(user_text)
    if total_chars >= PROMPT_SIZE_CRITICAL_CHARS:
        raise PromptTooLargeError(
            f"Prompt size {total_chars:,} chars >= critical threshold "
            f"{PROMPT_SIZE_CRITICAL_CHARS:,}; caller must compress user_text"
        )
    if total_chars >= PROMPT_SIZE_WARN_CHARS:
        logger.warning(
            "codex prompt size approaching limit: %s chars (warn=%s critical=%s) model=%s",
            f"{total_chars:,}", f"{PROMPT_SIZE_WARN_CHARS:,}",
            f"{PROMPT_SIZE_CRITICAL_CHARS:,}", model,
        )
    else:
        logger.info("codex prompt size=%s chars model=%s", f"{total_chars:,}", model)


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    message = str(exc).lower()
    return any(
        key in message
        for key in (
            "429",
            "rate limit",
            "quota",
            "timeout",
            "timed out",
            "server disconnected",
            "connection",
            "temporarily",
            "try again",
            "限流",
            "配额",
        )
    )


class CodexProvider:
    """LLMProvider impl backed by the ChatGPT Codex Responses SSE endpoint."""

    name = "codex"
    supports_vision = True

    def chat_json(
        self,
        *,
        system: str,
        user_text: str,
        images: list[bytes] | None = None,
        model: str | None = None,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        verbosity: str = "medium",
        response_format: dict[str, Any] | None = None,
        timeout: int | None = None,
        attempts: int = 3,
    ) -> dict[str, Any]:
        return chat_json(
            system=system,
            user_text=user_text,
            images=images,
            model=model,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            response_format=response_format,
            timeout=timeout,
            attempts=attempts,
        )

    def chat_text(
        self,
        *,
        system: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        verbosity: str = "medium",
        timeout: int | None = None,
        attempts: int = 3,
        retry_delay_seconds: float = 20.0,
    ) -> str:
        # 模块四生成报告时 SSE 流响应巨长（markdown 20K+ tokens），中途 peer
        # 断流是常见故障。复用 chat_json 的 retry 策略：可重试错误 → 退避重试。
        last_exc: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return chat(
                    system=system,
                    user_text=user_text,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    verbosity=verbosity,
                    timeout=timeout,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= attempts or not _is_retryable_error(exc):
                    raise
                sleep_seconds = retry_delay_seconds * attempt
                logger.warning("Codex text retry %d/%d after error: %s", attempt, attempts, exc)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
        raise RuntimeError(str(last_exc) if last_exc else "Codex text call failed")


def _friendly_error(code: int, raw: str) -> str:
    if code == 401:
        return "ChatGPT OAuth token expired. Re-run `codex login`."
    if code == 403:
        return "ChatGPT access denied. The account may need an active Plus/Pro subscription."
    if code == 429:
        return "ChatGPT quota or rate limit exceeded."
    return f"HTTP {code}: {raw[:500]}"
