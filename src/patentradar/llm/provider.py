"""LLM provider abstraction.

Two backends are supported:
- `codex`  — ChatGPT OAuth (Codex Responses SSE). Vision-capable.
- `openai` — any OpenAI-compatible Chat Completions endpoint (aihubmix /
             DeepSeek / vendor-hosted gateways). Vision opt-in via env.

Workers call `get_llm_provider().chat_json(...)`; backend selection is global
and driven by PATENTRADAR_LLM_BACKEND.
"""

from __future__ import annotations

import os
from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str
    supports_vision: bool

    def chat_json(
        self,
        *,
        system: str,
        user_text: str,
        images: list[bytes] | None = None,
        model: str | None = None,
        reasoning_effort: str = "high",
        verbosity: str = "medium",
        response_format: dict[str, Any] | None = None,
        timeout: int | None = None,
        attempts: int = 3,
    ) -> dict[str, Any]: ...

    def chat_text(
        self,
        *,
        system: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str = "high",
        verbosity: str = "medium",
        timeout: int | None = None,
    ) -> str: ...


_singleton: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return the process-wide LLM provider singleton."""
    global _singleton
    if _singleton is None:
        _singleton = _build()
    return _singleton


def reset_provider() -> None:
    """Drop the cached singleton — used by tests that twiddle env vars."""
    global _singleton
    _singleton = None


def _build() -> LLMProvider:
    backend = (os.getenv("PATENTRADAR_LLM_BACKEND") or "codex").strip().lower()
    if backend == "openai":
        from patentradar.llm.openai_compat import OpenAICompatibleProvider

        base_url = os.environ.get("PATENTRADAR_OPENAI_BASE_URL")
        api_key = os.environ.get("PATENTRADAR_OPENAI_API_KEY")
        if not base_url or not api_key:
            raise RuntimeError(
                "PATENTRADAR_LLM_BACKEND=openai requires both "
                "PATENTRADAR_OPENAI_BASE_URL and PATENTRADAR_OPENAI_API_KEY."
            )
        return OpenAICompatibleProvider(
            base_url=base_url,
            api_key=api_key,
            supports_vision=_truthy(os.getenv("PATENTRADAR_OPENAI_VISION", "false")),
        )
    if backend == "codex":
        from patentradar.llm.codex import CodexProvider

        return CodexProvider()
    raise RuntimeError(
        f"Unknown PATENTRADAR_LLM_BACKEND={backend!r}; expected 'codex' or 'openai'."
    )


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
