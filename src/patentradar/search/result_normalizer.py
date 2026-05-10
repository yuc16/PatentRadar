"""Helpers for normalized search results."""

from __future__ import annotations

from urllib.parse import urldefrag


def canonical_url(url: str) -> str:
    clean, _fragment = urldefrag(url.strip())
    return clean.rstrip("/")


def compact_snippet(value: str, *, max_chars: int = 800) -> str:
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
