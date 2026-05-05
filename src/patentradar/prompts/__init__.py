"""Prompt 文件加载工具。

所有长 prompt 以 Markdown 文件存放在本目录，便于阅读 / 优化 / 版本管理。
通过 ``load(name)`` 按文件名（不含扩展名）读取。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """读取 prompts/<name>.md 的内容。"""
    path = _DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    return path.read_text(encoding="utf-8").rstrip() + "\n"


def render(name: str, **kwargs: object) -> str:
    """读取 prompt 模板并以 ``str.format`` 填入变量。"""
    return load(name).format(**kwargs)
