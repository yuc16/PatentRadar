"""OpenAI-compatible Chat Completions provider.

Targets any vendor that exposes a standard `/chat/completions` endpoint —
aihubmix, DeepSeek's official API, vLLM gateways, etc. Non-streaming.

Differences vs CodexProvider:
- `reasoning_effort` / `verbosity` are dropped (most compatible endpoints
  reject unknown fields).
- `reasoning_content` on the response message (DeepSeek-style chain-of-thought)
  is discarded; only `content` is parsed.
- `response_format={"type":"json_schema","name":...,"strict":...,"schema":...}`
  is wrapped into OpenAI's standard `{"type":"json_schema","json_schema":{...}}`.
  If the server rejects strict schemas, we fall back once to
  `{"type":"json_object"}` for the same request.
- Vision input is gated by `supports_vision` (set via env). Callers must
  pre-check before passing images; if images are supplied to a provider that
  declared no vision support, we raise to fail loudly.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

import httpx

from patentradar.core.constants import (
    DEFAULT_MODEL,
    PROMPT_SIZE_CRITICAL_CHARS,
    PROMPT_SIZE_WARN_CHARS,
)
from patentradar.llm.codex import PromptTooLargeError, _is_retryable_error, _parse_json

logger = logging.getLogger(__name__)


def _check_prompt_size(system: str, user_text: str, model: str | None) -> None:
    """与 codex.py 同款 prompt-size 监控（PATENTRADAR_CONTEXT_LENGTH 派生）。
    openai-compat 后端面对的模型不同，但同样会因 prompt 过长触发服务端崩溃 /
    超时；这里复用同一组阈值（caller 端调 compress_payload_if_needed 兜底）。"""
    total_chars = len(system) + len(user_text)
    if total_chars >= PROMPT_SIZE_CRITICAL_CHARS:
        raise PromptTooLargeError(
            f"openai-compat prompt size {total_chars:,} chars >= "
            f"{PROMPT_SIZE_CRITICAL_CHARS:,}; caller must compress user_text"
        )
    if total_chars >= PROMPT_SIZE_WARN_CHARS:
        logger.warning(
            "openai-compat prompt size %s chars >= warn %s (model=%s)",
            f"{total_chars:,}", f"{PROMPT_SIZE_WARN_CHARS:,}", model,
        )

# aihubmix / 中转服务在 DeepSeek 长上下文请求里频繁出现 "Server disconnected
# without sending a response"（httpx.RemoteProtocolError）。这类断流跟 429
# 配额无关，是底层连接抖动，重试通常一次就能成功。我们对 OpenAI 兼容侧
# 单独抬高重试上限，并把断流场景的退避时间压短。
_MIN_OPENAI_ATTEMPTS = 6
_OPENAI_RETRY_BASE_SECONDS = 4.0


class OpenAIVisionUnsupportedError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        supports_vision: bool = False,
        timeout: int = 900,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.supports_vision = supports_vision
        self.default_timeout = timeout

    def chat_json(
        self,
        *,
        system: str,
        user_text: str,
        images: list[bytes] | None = None,
        model: str | None = None,
        reasoning_effort: str = "high",  # noqa: ARG002 — ignored by design
        verbosity: str = "medium",       # noqa: ARG002 — ignored by design
        response_format: dict[str, Any] | None = None,
        timeout: int | None = None,
        attempts: int = 3,
    ) -> dict[str, Any]:
        if images and not self.supports_vision:
            raise OpenAIVisionUnsupportedError(
                "Current OpenAI-compatible provider was configured without vision "
                "support (PATENTRADAR_OPENAI_VISION=false). Caller must drop images "
                "before invoking chat_json, or set PATENTRADAR_OPENAI_VISION=true "
                "if the chosen model accepts image input."
            )

        resolved_model = model or os.getenv("PATENTRADAR_MODEL") or DEFAULT_MODEL
        # openai 兼容后端不可靠地强制 json_schema（DeepSeek 直接 400 降级 json_object、
        # 中转站名义接受但不强制），schema 仅靠 response_format 传不到模型，会自创结构。
        # 故把 schema 显式注入 prompt，模型才看得到目标形状。
        system_with_schema = system + _schema_instruction(response_format)
        _check_prompt_size(system_with_schema, user_text, resolved_model)

        messages = [
            {"role": "system", "content": system_with_schema},
            {"role": "user", "content": _build_user_content(user_text, images)},
        ]
        request_body: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "stream": False,
        }
        wrapped_rf = _wrap_response_format(response_format) if response_format else None
        if wrapped_rf is not None:
            request_body["response_format"] = wrapped_rf

        effective_attempts = max(attempts, _MIN_OPENAI_ATTEMPTS)
        last_exc: Exception | None = None
        for attempt in range(1, effective_attempts + 1):
            try:
                text = self._call(request_body, timeout=timeout or self.default_timeout)
                return _parse_json(text)
            except _StrictSchemaRejected as exc:
                # One-shot fallback: retry the same request with json_object mode.
                # 保留 last_exc 让最终兜底 raise 时仍有可读错误信息。
                last_exc = exc
                logger.warning(
                    "OpenAI provider rejected json_schema strict mode; "
                    "falling back to json_object for this request."
                )
                request_body["response_format"] = {"type": "json_object"}
                # Re-loop to use the normal attempts budget on the fallback.
                continue
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= effective_attempts or not _is_retryable_error(exc):
                    raise
                sleep_seconds = _OPENAI_RETRY_BASE_SECONDS * attempt
                logger.warning(
                    "OpenAI provider retry %d/%d after error: %s",
                    attempt, effective_attempts, exc,
                )
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
        raise RuntimeError(str(last_exc) if last_exc else "OpenAI provider call failed")

    def chat_text(
        self,
        *,
        system: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str = "high",  # noqa: ARG002 — ignored by design
        verbosity: str = "medium",       # noqa: ARG002 — ignored by design
        timeout: int | None = None,
    ) -> str:
        resolved_model = model or os.getenv("PATENTRADAR_MODEL") or DEFAULT_MODEL
        _check_prompt_size(system, user_text, resolved_model)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        body: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "stream": False,
        }
        last_exc: Exception | None = None
        for attempt in range(1, _MIN_OPENAI_ATTEMPTS + 1):
            try:
                return self._call(body, timeout=timeout or self.default_timeout)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= _MIN_OPENAI_ATTEMPTS or not _is_retryable_error(exc):
                    raise
                time.sleep(_OPENAI_RETRY_BASE_SECONDS * attempt)
        raise RuntimeError(str(last_exc) if last_exc else "OpenAI provider text call failed")

    def _call(self, body: dict[str, Any], *, timeout: int) -> str:
        # Always force streaming so that the registered on_delta callback
        # (see patentradar.llm.stream) receives token deltas in real time.
        # Full content is reassembled before returning, so callers see the
        # same string they got from the non-streaming path.
        import json as _json

        body = {**body, "stream": True}
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        timeout_obj = httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0)
        from patentradar.llm.stream import emit_delta

        parts: list[str] = []
        with httpx.Client(timeout=timeout_obj) as client:
            with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code == 400:
                    raw = response.read().decode("utf-8", "ignore")
                    if _looks_like_schema_rejection(raw):
                        raise _StrictSchemaRejected(raw[:500])
                    raise RuntimeError(
                        f"OpenAI-compatible HTTP 400: {raw[:500]}"
                    )
                if response.status_code != 200:
                    raw = response.read().decode("utf-8", "ignore")
                    raise RuntimeError(
                        f"OpenAI-compatible HTTP {response.status_code}: {raw[:500]}"
                    )

                # SSE 帧由空行分隔，每帧内可有多行 data:。把同帧多个 data 行的
                # payload 用换行拼起来再 json.loads——大多数云厂商单行就够，但
                # 某些 (vLLM / 自建网关) 会把长 chunk 拆成多行。
                buffer_data: list[str] = []
                for line in response.iter_lines():
                    if line == "":
                        if not buffer_data:
                            continue
                        payload = "\n".join(buffer_data).strip()
                        buffer_data = []
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            event = _json.loads(payload)
                        except _json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            parts.append(content)
                            emit_delta(content)
                        continue
                    if line.startswith("data:"):
                        buffer_data.append(line[5:].lstrip())

        text = "".join(parts).strip()
        if not text:
            raise RuntimeError("OpenAI-compatible stream returned empty content")
        return text


class _StrictSchemaRejected(RuntimeError):
    pass


def _build_user_content(text: str, images: list[bytes] | None) -> Any:
    if not images:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for image in images:
        encoded = base64.b64encode(image).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
    return parts


def _wrap_response_format(rf: dict[str, Any]) -> dict[str, Any]:
    """Convert the worker's response_format dict into OpenAI's wire format.

    Workers currently emit `{"type":"json_schema","name":"X","strict":True,"schema":{...}}`
    — that shape mirrors the Codex Responses `text.format` field. The standard
    OpenAI Chat Completions API expects the same payload one layer deeper under
    `json_schema`. Anything else (e.g. `{"type":"json_object"}`) passes through.
    """
    if rf.get("type") != "json_schema":
        return rf
    if "json_schema" in rf:  # already in wrapped form
        return rf
    inner = {key: value for key, value in rf.items() if key != "type"}
    return {"type": "json_schema", "json_schema": inner}


def _schema_instruction(response_format: dict[str, Any] | None) -> str:
    """把 json_schema 渲染成 prompt 文本，让弱后端（无 API 层 schema 强制）也知道
    目标输出形状。非 json_schema（如 json_object）或无 schema 时返回空串。
    刻意使用小写 "json" 字样——DeepSeek 的 json_object 模式要求 prompt 含字面 "json"。
    """
    if not response_format or response_format.get("type") != "json_schema":
        return ""
    schema = response_format.get("schema")
    if schema is None and isinstance(response_format.get("json_schema"), dict):
        schema = response_format["json_schema"].get("schema")
    if not schema:
        return ""
    return (
        "\n\n你必须只返回一个 json 对象，严格符合以下 JSON Schema："
        "顶层字段名、嵌套层级、类型必须完全一致，不要新增 schema 之外的字段，"
        "不要把字段塞进自创的包装层（如 metadata），不要 markdown 代码块围栏，"
        "不要任何解释文字。\nJSON Schema：\n" + json.dumps(schema, ensure_ascii=False)
    )


def _looks_like_schema_rejection(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "json_schema",
            "response_format",
            "strict",
            "unsupported",
        )
    )
