"""三个搜索 Agent 实现（PRD §6.3）。

- ``deepseek``: 中文公开资料视角（主搜索 = bocha + tavily）
- ``kimi``    : 官方 / 长文资料视角（主搜索 = tavily + jina）
- ``glm``     : 语义扩展视角（主搜索 = exa + brave）

每个 Agent 共享同一个 ``SearchAgent`` 类，仅参数化以下三项：
1. LLM 端点（不同 provider 不同 model）
2. 视角 system prompt（候选发现阶段差异化）
3. 主搜索源集合（候选发现阶段差异化）

证据检索阶段使用共享 ``search.pool``，无差异化。
"""

from .base import SearchAgent  # noqa: F401
from .perspectives import PERSPECTIVES, get_perspective  # noqa: F401
