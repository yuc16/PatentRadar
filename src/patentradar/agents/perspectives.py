"""三个搜索 Agent 的视角配置。"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config


@dataclass(frozen=True)
class AgentPerspective:
    name: str  # 内部标识 (deepseek / kimi / glm)
    display_name: str  # 输出 JSON 中的 agent_name
    perspective_label: str  # PRD §6.3 视角描述
    primary_engines: tuple[str, ...]  # 候选发现阶段的主搜索源
    query_gen_prompt: str  # prompt 文件名（不含扩展名）
    llm_endpoint: config.LLMEndpoint
    # 中国行业媒体路由：开启后，会按 task.industry_tag 追加 site: 限定 query，
    # 并在证据补搜阶段对候选公司调用巨潮资讯 (cninfo) 查公告 / 年报
    cn_industry_routing: bool = False


PERSPECTIVES: dict[str, AgentPerspective] = {
    "deepseek": AgentPerspective(
        name="deepseek",
        display_name="deepseek_agent",
        perspective_label="中文公开资料视角",
        primary_engines=("bocha", "tavily"),
        query_gen_prompt="agent_query_gen_deepseek",
        llm_endpoint=config.AGENT_3,
        cn_industry_routing=True,
    ),
    "kimi": AgentPerspective(
        name="kimi",
        display_name="kimi_agent",
        perspective_label="官方/长文资料视角",
        # Jina 当前不可用 → 用 Exa（contents 能抓 PDF/长文）作为长文视角第二源
        primary_engines=("tavily", "exa"),
        query_gen_prompt="agent_query_gen_kimi",
        llm_endpoint=config.AGENT_2,
    ),
    "glm": AgentPerspective(
        name="glm",
        display_name="glm_agent",
        perspective_label="语义扩展视角",
        primary_engines=("exa", "brave"),
        query_gen_prompt="agent_query_gen_glm",
        llm_endpoint=config.AGENT_1,
    ),
}


def get_perspective(name: str) -> AgentPerspective:
    if name not in PERSPECTIVES:
        raise ValueError(
            f"未知 agent perspective: {name!r}, 合法值: {list(PERSPECTIVES)}"
        )
    return PERSPECTIVES[name]
