"""中国行业媒体白名单加载与 ``site:`` 限定 query 拼接。

白名单存放在项目根目录 ``data/cn_industry_sites/`` 下，每个 JSON 一个领域。
``industry_tag`` 字段必须等于文件名（不含扩展名）。

业务流程：阶段 1 拆解时由 LLM 给专利打 ``industry_tag``；阶段 2 DeepSeek Agent
据此选取站点白名单，把站点限定追加到部分 query，提升中文垂类召回率。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Site:
    domain: str
    name: str = ""
    type: str = ""


@dataclass(frozen=True)
class IndustryGroup:
    industry_tag: str
    label: str
    sites: tuple[Site, ...]


_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "cn_industry_sites"
GENERAL_TAG = "general"


@lru_cache(maxsize=1)
def _load_all() -> dict[str, IndustryGroup]:
    out: dict[str, IndustryGroup] = {}
    if not _DATA_DIR.exists():
        logger.warning("行业站点白名单目录不存在: %s", _DATA_DIR)
        return out
    for path in sorted(_DATA_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("加载白名单失败 %s: %s", path.name, exc)
            continue
        tag = str(data.get("industry_tag") or path.stem).strip()
        sites = tuple(
            Site(
                domain=str(s.get("domain") or "").strip().lower(),
                name=str(s.get("name") or "").strip(),
                type=str(s.get("type") or "").strip(),
            )
            for s in data.get("sites", [])
            if str(s.get("domain") or "").strip()
        )
        out[tag] = IndustryGroup(
            industry_tag=tag,
            label=str(data.get("label") or tag),
            sites=sites,
        )
    return out


def known_tags() -> list[str]:
    """返回所有可用的 ``industry_tag``（不含 general）。"""
    return [t for t in _load_all() if t != GENERAL_TAG]


def get_group(industry_tag: str | None) -> IndustryGroup | None:
    if not industry_tag:
        return None
    return _load_all().get(industry_tag.strip().lower())


def load_sites(industry_tag: str | None) -> list[Site]:
    """返回 ``industry_tag`` + ``general`` 合并去重后的站点列表。

    若 ``industry_tag`` 未知，仅返回 general。
    """
    out: list[Site] = []
    seen: set[str] = set()

    def _extend(group: IndustryGroup | None) -> None:
        if not group:
            return
        for s in group.sites:
            if s.domain and s.domain not in seen:
                seen.add(s.domain)
                out.append(s)

    _extend(get_group(industry_tag))
    _extend(get_group(GENERAL_TAG))
    return out


def build_site_filter(sites: list[Site] | tuple[Site, ...], *, max_sites: int = 8) -> str:
    """把站点列表拼成 Bing/Bocha 风格的 ``(site:a.com OR site:b.com)`` 限定。

    Bing 对 ``site:`` 数量有限制，默认取前 ``max_sites`` 个。空列表返回空串。
    """
    chosen = list(sites)[:max_sites]
    if not chosen:
        return ""
    return "(" + " OR ".join(f"site:{s.domain}" for s in chosen) + ")"


def split_sites_by_priority(
    sites: list[Site] | tuple[Site, ...],
    *,
    max_sites: int = 8,
) -> tuple[list[Site], list[Site]]:
    """把站点拆为「行业媒体 / 行业协会 / 政府」 与 「厂商官网」 两组。

    返回 (媒体组, 厂商组)；分别用于做两条不同侧重的 query。
    """
    media: list[Site] = []
    vendor: list[Site] = []
    for s in sites:
        if "厂商官网" in s.type:
            vendor.append(s)
        else:
            media.append(s)
    return media[:max_sites], vendor[:max_sites]
