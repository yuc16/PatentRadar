"""Controller LLM entrypoint with Kimi fallback.

GPT-5.5 is still the preferred controller/reviewer model. When ChatGPT OAuth is
temporarily unavailable or quota-limited, this module retries GPT three times
and then falls back to the configured Kimi Agent endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import config
from . import client, codex

logger = logging.getLogger(__name__)

_GPT_ATTEMPTS = 3


def chat_json(
    *,
    system: str,
    user_text: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    reasoning_effort: str = "medium",
    verbosity: str = "medium",
    timeout: int | None = None,
    fallback_label: str = "controller",
) -> dict[str, Any]:
    """Return JSON from GPT-5.5, falling back to Kimi after 3 GPT attempts."""
    try:
        payload = codex.chat_json(
            system=system,
            user_text=user_text,
            images=images,
            model=model,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            timeout=timeout,
            attempts=_GPT_ATTEMPTS,
        )
        payload.setdefault("_llm_model_used", f"codex:{model or 'gpt-5.5'}")
        return payload
    except Exception as exc:  # noqa: BLE001
        if not _should_fallback_to_kimi(exc):
            raise
        if not config.AGENT_2.is_configured:
            raise RuntimeError(
                f"GPT-5.5 调用失败，且 Kimi 兜底端点 SEARCH_AGENT_2 未配置完整: {exc}"
            ) from exc
        logger.warning(
            "[%s] GPT-5.5 failed after %d attempts; fallback to Kimi endpoint=%s model=%s images=%d error=%s",
            fallback_label,
            _GPT_ATTEMPTS,
            config.AGENT_2.base_url,
            config.AGENT_2.model,
            len(images or []),
            exc,
        )
        if images:
            payload = client.chat_json_multimodal(
                config.AGENT_2,
                system=system,
                user=user_text,
                images=images,
                temperature=0.1,
                timeout=timeout or config.AGENT_LLM_TIMEOUT,
            )
        else:
            payload = client.chat_json(
                config.AGENT_2,
                system=system,
                user=user_text,
                temperature=0.1,
                timeout=timeout or config.AGENT_LLM_TIMEOUT,
            )
        payload.setdefault(
            "_llm_model_used",
            f"{config.AGENT_2.model} (Kimi fallback after GPT-5.5 quota/limit)",
        )
        return payload


def probe_chatgpt_quota(*, model: str | None = None) -> tuple[bool, str]:
    """Lightweight ChatGPT OAuth availability probe."""
    try:
        payload = codex.chat_json(
            system="只输出 JSON。",
            user_text='请只输出 {"ok": true}',
            model=model,
            reasoning_effort="low",
            verbosity="low",
            timeout=60,
            attempts=1,
            retry_delay_seconds=0,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return bool(payload.get("ok")), str(payload)


def _should_fallback_to_kimi(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        key in msg
        for key in (
            "401",
            "403",
            "429",
            "oauth",
            "token",
            "订阅",
            "拒绝访问",
            "限流",
            "配额",
            "rate limit",
            "quota",
            "server disconnected",
            "connection",
            "timeout",
            "timed out",
            "temporarily",
            "try again",
        )
    )
