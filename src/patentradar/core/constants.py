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


@dataclass(frozen=True)
class TechnologyTag:
    name: str
    description: str
    typical_objects: tuple[str, ...]


_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "technology_tags.toml"


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
            )
        )
    if not tags:
        raise ValueError("technology_tags.toml must define at least one tag")
    return tuple(tags)


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
