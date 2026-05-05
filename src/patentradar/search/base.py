"""搜索 API 公共数据结构与异常。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchHit:
    """单条搜索结果（统一表示）。"""

    url: str
    title: str = ""
    snippet: str = ""
    source: str = ""  # 哪个搜索引擎给出的：bocha / exa / brave / tavily / jina
    raw: dict = field(default_factory=dict)
    score: Optional[float] = None
    published_date: Optional[str] = None


@dataclass
class ExtractedPage:
    """正文抽取结果。"""

    url: str
    title: str = ""
    text: str = ""  # 抽取后的纯文本 / Markdown
    source: str = ""  # jina / tavily_extract / exa_contents
    raw: dict = field(default_factory=dict)


class SearchError(RuntimeError):
    """搜索 API 调用失败。"""

    def __init__(self, engine: str, message: str):
        super().__init__(f"[{engine}] {message}")
        self.engine = engine
