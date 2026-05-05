"""集中加载 .env 配置。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class LLMEndpoint:
    name: str
    api_key: str
    base_url: str
    model: str
    context_window: int = 128_000  # 默认窗口；从 .env 读

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


def _ep(prefix: str, display_name: str, default_window: int = 128_000) -> LLMEndpoint:
    return LLMEndpoint(
        name=display_name,
        api_key=os.getenv(f"{prefix}_API_KEY", "").strip(),
        base_url=os.getenv(f"{prefix}_BASE_URL", "").strip(),
        model=os.getenv(f"{prefix}_MODEL", "").strip(),
        context_window=int(
            os.getenv(f"{prefix}_CONTEXT_WINDOW", str(default_window)).strip() or default_window
        ),
    )


REVIEWER = _ep("REVIEWER", "reviewer", default_window=400_000)
AGENT_1 = _ep("SEARCH_AGENT_1", "agent1_glm", default_window=128_000)
AGENT_2 = _ep("SEARCH_AGENT_2", "agent2_kimi", default_window=200_000)
AGENT_3 = _ep("SEARCH_AGENT_3", "agent3_deepseek", default_window=128_000)

SEARCH_KEYS = {
    "bocha": os.getenv("BOCHA_API_KEY", "").strip(),
    "exa": os.getenv("EXA_API_KEY", "").strip(),
    "brave": os.getenv("BRAVE_API_KEY", "").strip(),
    "tavily": os.getenv("TAVILY_API_KEY", "").strip(),
}

DECOMPOSER_LLM = os.getenv("DECOMPOSER_LLM", "reviewer").strip().lower()
PATENT_FETCH_TIMEOUT = int(os.getenv("PATENT_FETCH_TIMEOUT", "30"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
AGENT_LLM_TIMEOUT = int(os.getenv("AGENT_LLM_TIMEOUT", "240"))

# GPT-5.5 推理强度（PRD 中"reasoning_effort"），从 .env 读，由 CLI / 调用点使用
REVIEWER_REASONING_EFFORT = (
    os.getenv("REVIEWER_REASONING_EFFORT", "medium").strip().lower() or "medium"
)
DECOMPOSER_REASONING_EFFORT = (
    os.getenv("DECOMPOSER_REASONING_EFFORT", "medium").strip().lower() or "medium"
)

# 上下文动态压缩：预算 = ctx_window * 比例 - 输出预留
COMPACTOR_BUDGET_RATIO = float(os.getenv("COMPACTOR_BUDGET_RATIO", "0.7"))
COMPACTOR_OUTPUT_RESERVE = int(os.getenv("COMPACTOR_OUTPUT_RESERVE", "4096"))
# 长文压缩用的 LLM 端点（便宜模型即可）
COMPACTOR_LLM = os.getenv("COMPACTOR_LLM", "agent3").strip().lower() or "agent3"

# 目录约定：
#   data/      用户输入（候选专利清单.xlsx 等）
#   tmp/       中间产物缓存（task_package.json / agent_*.json / final_report.json）
#   output/    最终用户产物（final_report.md + runs/*.log）
DATA_DIR = PROJECT_ROOT / "data"
INTERMEDIATE_DIR = PROJECT_ROOT / "tmp"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _llm_mapping() -> dict[str, LLMEndpoint]:
    return {
        "reviewer": REVIEWER,
        "agent1": AGENT_1,
        "agent2": AGENT_2,
        "agent3": AGENT_3,
    }


def get_decomposer_endpoint() -> LLMEndpoint:
    ep = _llm_mapping().get(DECOMPOSER_LLM, REVIEWER)
    if not ep.is_configured:
        raise RuntimeError(
            f"DECOMPOSER_LLM={DECOMPOSER_LLM} 对应的端点未配置完整 (api_key/base_url/model)"
        )
    return ep


def get_compactor_endpoint() -> LLMEndpoint:
    """长文摘要压缩用的便宜 LLM 端点。"""
    ep = _llm_mapping().get(COMPACTOR_LLM, AGENT_3)
    if not ep.is_configured:
        # fallback 到任意已配置的 agent
        for cand in (AGENT_3, AGENT_1, AGENT_2):
            if cand.is_configured:
                return cand
        raise RuntimeError("compactor 找不到任何已配置的 LLM 端点")
    return ep
