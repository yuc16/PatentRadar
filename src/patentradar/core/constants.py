"""Project-wide constants and environment-backed settings."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("PATENTRADAR_MODEL", "gpt-5.5")
DEFAULT_CONTEXT_LENGTH = int(os.getenv("PATENTRADAR_CONTEXT_LENGTH", "258000"))
DEFAULT_REASONING_EFFORT = os.getenv("PATENTRADAR_REASONING_EFFORT", "high")
GOOGLE_PATENTS_BASE = "https://patents.google.com/patent"

# Country code → (display name, working language for prompts/search).
# Used by PatentInfo to auto-derive country from publication_no prefix.
PATENT_COUNTRY_CODES: dict[str, tuple[str, str]] = {
    "CN": ("中国", "zh"),
    "US": ("美国", "en"),
    "EP": ("欧洲专利局", "en"),
    "JP": ("日本", "ja"),
    "KR": ("韩国", "ko"),
    "DE": ("德国", "de"),
    "GB": ("英国", "en"),
    "FR": ("法国", "fr"),
    "WO": ("PCT 国际申请", "en"),
    "CA": ("加拿大", "en"),
    "AU": ("澳大利亚", "en"),
    "IN": ("印度", "en"),
    "RU": ("俄罗斯", "ru"),
    "TW": ("中国台湾", "zh"),
    "HK": ("中国香港", "zh"),
}


@dataclass(frozen=True)
class RecommendedSite:
    """模块二/三主动搜索的垂类网站推荐项。"""
    url: str  # 网站根域名（如 https://batteryfinds.com），src 端用作 `site:host` 修饰
    description: str  # 该站点的能力/适用场景，方便 LLM 决定何时优先搜


@dataclass(frozen=True)
class TechnologyTag:
    name: str
    description: str
    typical_objects: tuple[str, ...]
    recommended_sites: tuple[RecommendedSite, ...] = ()


_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "technology_tags.toml"
# 注意：skills/patentradar/configs/technology_tags.toml 是这一份的副本（skill
# 单独移植时需要带走那份）。**编辑标签或网站推荐时两份都要改**，否则会出现
# Python pipeline 和 skill agent 看到的标签集合不一致。


def _parse_sites(items: list[dict] | None) -> tuple[RecommendedSite, ...]:
    return tuple(
        RecommendedSite(
            url=entry["url"],
            description=entry.get("description", ""),
        )
        for entry in (items or [])
        if entry.get("url")
    )


@lru_cache(maxsize=1)
def load_technology_tags() -> tuple[TechnologyTag, ...]:
    """Load tag metadata from configs/technology_tags.toml so tags can be tuned
    without touching code or prompt files. constants module, decompose prompt,
    and json-schema enum all read from this single source."""
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"technology_tags.toml not found at {_CONFIG_PATH}")
    with _CONFIG_PATH.open("rb") as fh:
        data = tomllib.load(fh)
    tags: list[TechnologyTag] = []
    for entry in data.get("tags", []):
        tags.append(
            TechnologyTag(
                name=entry["name"],
                description=entry.get("description", ""),
                typical_objects=tuple(entry.get("typical_objects", []) or []),
                recommended_sites=_parse_sites(entry.get("recommended_sites")),
            )
        )
    if not tags:
        raise ValueError("technology_tags.toml must define at least one tag")
    return tuple(tags)


@lru_cache(maxsize=1)
def load_universal_sites() -> tuple[RecommendedSite, ...]:
    """所有 tag 通用的垂类证据站点（顶层 [[universal_sites]]）。模块二/三搜索时
    不论本专利属于哪个 tag 都会 site: 修饰跑一遍这些站点。"""
    if not _CONFIG_PATH.exists():
        return ()
    with _CONFIG_PATH.open("rb") as fh:
        data = tomllib.load(fh)
    return _parse_sites(data.get("universal_sites"))


def get_recommended_sites_for_tag(tag_name: str) -> tuple[RecommendedSite, ...]:
    """返回某 tag 自己的 recommended_sites + 所有 universal_sites 的合并集。
    顺序：tag 专属在前（更高优先级），universal 在后；按 url 去重。"""
    seen: set[str] = set()
    out: list[RecommendedSite] = []
    for tag in load_technology_tags():
        if tag.name == tag_name:
            for site in tag.recommended_sites:
                if site.url not in seen:
                    seen.add(site.url)
                    out.append(site)
            break
    for site in load_universal_sites():
        if site.url not in seen:
            seen.add(site.url)
            out.append(site)
    return tuple(out)


def _technology_tag_names() -> list[str]:
    return [tag.name for tag in load_technology_tags()]


# Module-level alias kept for backward compatibility with existing imports.
# Resolves to a fresh list each access so config edits take effect on reload.
TECHNOLOGY_TAGS = _technology_tag_names()


def render_technology_tags_markdown() -> str:
    """Markdown bullet list used to substitute into the decompose prompt."""
    lines: list[str] = []
    for tag in load_technology_tags():
        objects = "、".join(tag.typical_objects)
        if objects:
            lines.append(f"- {tag.name}：{tag.description}典型对象：{objects}。")
        else:
            lines.append(f"- {tag.name}：{tag.description}")
    return "\n".join(lines)
