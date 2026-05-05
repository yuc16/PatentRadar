"""ChatGPT Plus/Pro OAuth (Codex) 客户端 - 同步 + 多模态版本。

通过读取 ~/.codex/auth.json 中的 access_token + account_id 调用
https://chatgpt.com/backend-api/codex/responses (SSE 流)，把 system + user
转换为 Codex Responses API 的 instructions + input 格式。

支持 input_image（base64 data URL）实现多模态。
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Iterator

import httpx

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_MODEL = "gpt-5.5"
AUTH_PATH = Path.home() / ".codex" / "auth.json"


class CodexAuthError(RuntimeError):
    pass


def _load_token() -> tuple[str, str]:
    if not AUTH_PATH.exists():
        raise CodexAuthError(
            f"未找到 {AUTH_PATH}。请先用官方 codex CLI 执行 `codex login` 登录 ChatGPT 账号。"
        )
    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexAuthError(f"读取 {AUTH_PATH} 失败: {exc}") from exc
    tokens = data.get("tokens") or {}
    access = tokens.get("access_token") or ""
    account_id = tokens.get("account_id") or ""
    if not access:
        raise CodexAuthError(f"{AUTH_PATH} 中没有 access_token。请重跑 `codex login`。")
    return access, account_id


def _headers() -> dict[str, str]:
    access, account_id = _load_token()
    h = {
        "Authorization": f"Bearer {access}",
        "OpenAI-Beta": "responses=experimental",
        "originator": os.getenv("OPENAI_CODEX_ORIGINATOR", "patent-radar"),
        "User-Agent": "patent-radar (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }
    if account_id:
        h["chatgpt-account-id"] = account_id
    return h


def _img_to_data_url(image_bytes: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def chat(
    *,
    system: str,
    user_text: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    reasoning_effort: str = "medium",
    verbosity: str = "medium",
    timeout: int = 240,
) -> str:
    """单轮调用 Codex Responses。返回模型输出的纯文本。"""
    model = model or os.getenv("REVIEWER_MODEL", "").strip() or DEFAULT_MODEL

    user_content: list[dict[str, Any]] = [{"type": "input_text", "text": user_text}]
    for img in images or []:
        user_content.append(
            {"type": "input_image", "image_url": _img_to_data_url(img)}
        )

    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "stream": True,
        "instructions": system,
        "input": [{"role": "user", "content": user_content}],
        "text": {"verbosity": verbosity},
        "reasoning": {"effort": reasoning_effort, "summary": "auto"},
        "include": ["reasoning.encrypted_content"],
        "tool_choice": "none",
        "parallel_tool_calls": False,
    }

    timeout_obj = httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0)
    parts: list[str] = []
    with httpx.Client(timeout=timeout_obj) as client:
        with client.stream(
            "POST", CODEX_URL, headers=_headers(), json=body
        ) as resp:
            if resp.status_code != 200:
                raw = resp.read().decode("utf-8", "ignore")
                raise RuntimeError(_friendly_error(resp.status_code, raw))
            for event in _iter_sse(resp):
                et = event.get("type")
                if et == "response.output_text.delta":
                    delta = event.get("delta") or ""
                    if delta:
                        parts.append(delta)
                elif et in {"error", "response.failed"}:
                    raise RuntimeError(
                        f"Codex 流错误: {json.dumps(event, ensure_ascii=False)[:300]}"
                    )
    return "".join(parts)


def chat_json(
    *,
    system: str,
    user_text: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    reasoning_effort: str = "medium",
    verbosity: str = "medium",
    timeout: int = 240,
) -> dict[str, Any]:
    text = chat(
        system=system,
        user_text=user_text,
        images=images,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
        timeout=timeout,
    )
    return _parse_json(text)


# =============== 工具 ===============


def _iter_sse(response: httpx.Response) -> Iterator[dict[str, Any]]:
    buffer: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if not buffer:
                continue
            payload_lines = [s[5:].strip() for s in buffer if s.startswith("data:")]
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
        s = text.find("{")
        e = text.rfind("}")
        if s >= 0 and e > s:
            return json.loads(text[s : e + 1])
        raise


def _friendly_error(code: int, raw: str) -> str:
    if code == 401:
        return "ChatGPT OAuth token 失效或过期，请重跑 `codex login`。"
    if code == 403:
        return "ChatGPT 拒绝访问：账号需要有效的 ChatGPT Plus/Pro 订阅。"
    if code == 429:
        return "ChatGPT 配额超限或限流，请稍后重试。"
    return f"HTTP {code}: {raw[:500]}"
