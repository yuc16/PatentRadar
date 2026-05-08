"""统一的 OpenAI 兼容客户端封装。"""
from __future__ import annotations

import base64
import json
from typing import Any

from openai import OpenAI

from ..config import LLM_TIMEOUT, LLMEndpoint


def make_client(ep: LLMEndpoint, *, timeout: int | None = None) -> OpenAI:
    return OpenAI(
        api_key=ep.api_key,
        base_url=ep.base_url,
        timeout=timeout or LLM_TIMEOUT,
    )


def chat_text(
    ep: LLMEndpoint,
    *,
    system: str,
    user: str,
    temperature: float = 0.1,
    timeout: int | None = None,
) -> str:
    """调用 LLM 返回纯文本（不解析 JSON）。"""
    client = make_client(ep, timeout=timeout)
    resp = client.chat.completions.create(
        model=ep.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def chat_json(
    ep: LLMEndpoint,
    *,
    system: str,
    user: str,
    temperature: float = 0.1,
    timeout: int | None = None,
) -> Any:
    """调用 LLM 并强制解析 JSON 返回。

    优先尝试 response_format=json_object；若上游不支持则回退到
    "在 prompt 里要求只输出 JSON" + 容错解析。
    """
    client = make_client(ep, timeout=timeout)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw: str = ""
    try:
        resp = client.chat.completions.create(
            model=ep.model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
    except Exception:
        resp = client.chat.completions.create(
            model=ep.model,
            messages=messages,
            temperature=temperature,
        )
        raw = resp.choices[0].message.content or ""

    try:
        return _parse_json_loose(raw)
    except json.JSONDecodeError:
        retry_messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {
                "role": "user",
                "content": (
                    "你的上一轮输出不是合法 JSON，无法被程序解析。请只输出一个合法 JSON 对象，"
                    "不要包含 Markdown、解释文字或代码块。"
                ),
            },
        ]
        resp = client.chat.completions.create(
            model=ep.model,
            messages=retry_messages,
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        return _parse_json_loose(raw)


def chat_json_multimodal(
    ep: LLMEndpoint,
    *,
    system: str,
    user: str,
    images: list[bytes] | None = None,
    temperature: float = 0.1,
    timeout: int | None = None,
) -> Any:
    """调用支持 OpenAI-compatible vision payload 的 LLM 并解析 JSON。"""
    client = make_client(ep, timeout=timeout)
    content: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for img in images or []:
        data_url = "data:image/png;base64," + base64.b64encode(img).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]
    raw: str = ""
    try:
        resp = client.chat.completions.create(
            model=ep.model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
    except Exception:
        resp = client.chat.completions.create(
            model=ep.model,
            messages=messages,
            temperature=temperature,
        )
        raw = resp.choices[0].message.content or ""

    try:
        return _parse_json_loose(raw)
    except json.JSONDecodeError:
        retry_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "你的上一轮输出不是合法 JSON，无法被程序解析。请只输出一个合法 JSON 对象，"
                    "不要包含 Markdown、解释文字或代码块。"
                ),
            },
        ]
        resp = client.chat.completions.create(
            model=ep.model,
            messages=retry_messages,
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        return _parse_json_loose(raw)


def _parse_json_loose(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        # 去除 ```json ... ``` 包裹
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 截取首个 { ... } 块
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
