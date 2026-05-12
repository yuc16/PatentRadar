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
import logging
import os
import time
from typing import Any

import httpx

from patentradar.core.constants import DEFAULT_MODEL
from patentradar.llm.codex import _is_retryable_error, _parse_json

logger = logging.getLogger(__name__)

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

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": _build_user_content(user_text, images)},
        ]
        request_body: dict[str, Any] = {
            "model": model or os.getenv("PATENTRADAR_MODEL") or DEFAULT_MODEL,
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
            except _StrictSchemaRejected:
                # One-shot fallback: retry the same request with json_object mode.
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
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        body: dict[str, Any] = {
            "model": model or os.getenv("PATENTRADAR_MODEL") or DEFAULT_MODEL,
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
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout_obj = httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0)
        with httpx.Client(timeout=timeout_obj) as client:
            response = client.post(url, headers=headers, json=body)
        if response.status_code == 400 and _looks_like_schema_rejection(response.text):
            raise _StrictSchemaRejected(response.text[:500])
        if response.status_code != 200:
            raise RuntimeError(
                f"OpenAI-compatible HTTP {response.status_code}: {response.text[:500]}"
            )
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenAI-compatible empty choices: {str(data)[:500]}")
        message = choices[0].get("message") or {}
        # DeepSeek and other reasoning models return `reasoning_content` separately;
        # we intentionally ignore it and only consume `content`.
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                f"OpenAI-compatible missing message.content: {str(data)[:500]}"
            )
        return content


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
