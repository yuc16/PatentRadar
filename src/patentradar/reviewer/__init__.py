"""阶段 4：GPT-5.5 最终复核（PRD §11）。

新版：跨候选合并去重交给 GPT-5.5；merger.py 仅保留为兼容入口（不再被 reviewer 调用）。
"""

from .merger import merge_agent_outputs  # noqa: F401  - 兼容保留
from .reviewer import review_agent_outputs  # noqa: F401  - 主入口
