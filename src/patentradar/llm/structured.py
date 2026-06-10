"""结构化输出 helper：生成 JSON → 解析校验 → 失败则把错误回喂进 prompt 重生成。

provider 层的 ``chat_json`` 保持单发（生成 + 解析），这一层负责「校验重试 +
错误回喂」。意义：弱后端（DeepSeek / aihubmix 走 json_object，没有 API 层
json_schema 强制）偶尔会吐出字段不符 / 语法瑕疵的 JSON，这里把校验错误写回
prompt 让模型自我纠正，最多重生成 ``repair_attempts`` 次。codex 后端 API 层强制
schema，这个循环几乎不触发。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, TypeVar

from pydantic import ValidationError

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.core.exceptions import LLMOutputError
from patentradar.llm import get_llm_provider

logger = logging.getLogger(__name__)

T = TypeVar("T")

# parse(payload) 因「模型给的 payload 形状不对」而失败 → 重生成能救：字段不符
# schema / worker 业务校验拒绝（字段缺失、tag 非法、claim 数对不上…），以及 worker
# 后处理（如 _normalize_candidate_ids）在 Pydantic 校验*之前*对错构 payload（顶层
# 字段为 null / 类型不符）抛的 TypeError/KeyError/AttributeError/IndexError。
# 注意：这些只在 parse() 周围捕获——provider.chat_json() 自身的集成异常（同名
# 的 KeyError/TypeError 等）不在此列，必须原样上抛而非误判为模型输出错误反复重生成。
_PARSE_FAILURES = (
    ValidationError,
    LLMOutputError,
    TypeError,
    KeyError,
    AttributeError,
    IndexError,
)

# 回喂给下一轮 prompt 的修正说明上限。worker 的 LLMOutputError 常把整份 payload
# 塞进消息，原样追加会让本就接近上下文上限的请求（evidence / full_claim_chart）
# 触发 PromptTooLargeError 使修复循环失效，故只回喂限长的错误摘要。
_CORRECTION_MAX_CHARS = 800


def generate_validated(
    *,
    system: str,
    user_text: str,
    parse: Callable[[dict[str, Any]], T],
    response_format: dict[str, Any] | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    verbosity: str = "medium",
    images: list[bytes] | None = None,
    timeout: int = 900,
    attempts: int = 3,
    repair_attempts: int = 2,
) -> T:
    """生成结构化输出并用 ``parse`` 校验；校验失败则回喂错误重生成。

    ``parse`` 接收解析后的 dict，做后处理 + Pydantic 校验，返回模型对象，
    失败时抛 ``ValidationError`` 或 ``LLMOutputError``。``attempts`` 是 provider
    层的网络重试预算；``repair_attempts`` 是本层因「输出不合规」额外重生成的次数。
    """
    provider = get_llm_provider()
    correction = ""
    last_exc: Exception | None = None
    total = repair_attempts + 1
    for round_idx in range(1, total + 1):
        # provider.chat_json 与 parse 分两段 try：provider 自身的集成异常（KeyError /
        # TypeError 等）不被下面 _PARSE_FAILURES 误吞、直接上抛；只有「模型输出不可
        # 解析」(JSONDecodeError) 和「payload 形状不对」(parse 失败) 才触发重生成。
        try:
            payload = provider.chat_json(
                system=system,
                user_text=user_text + correction,
                images=images,
                model=model,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
                response_format=response_format,
                timeout=timeout,
                attempts=attempts,
            )
        except json.JSONDecodeError as exc:
            last_exc = exc  # 模型吐了不可解析的 JSON（provider 的兜底也救不回）
        else:
            try:
                return parse(payload)
            except _PARSE_FAILURES as exc:
                last_exc = exc  # payload 形状不对（schema / 后处理）
        if round_idx >= total:
            break
        logger.warning(
            "结构化输出不合规（第 %d/%d 轮），回喂错误重生成：%s",
            round_idx, total, str(last_exc)[:200],
        )
        correction = _correction_note(last_exc)
    assert last_exc is not None
    raise last_exc


def _correction_note(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        detail = "schema 校验错误：\n" + "\n".join(
            f"- {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
    elif isinstance(exc, json.JSONDecodeError):
        detail = f"JSON 语法错误：{exc}"
    else:  # LLMOutputError / TypeError / KeyError / ...
        detail = f"输出错误：{exc}"
    if len(detail) > _CORRECTION_MAX_CHARS:
        detail = detail[:_CORRECTION_MAX_CHARS] + " …（错误信息过长已截断）"
    return (
        "\n\n[修正要求] 你上一次的输出被拒绝，原因是" + detail + "\n"
        "请只返回一个修正后、完整且严格符合所需 schema 的 JSON 对象，"
        "不要任何解释文字或 markdown 代码块围栏。"
    )
