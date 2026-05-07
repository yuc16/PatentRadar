"""Run-scoped search caches shared by agents and reviewer."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import pool
from .base import ExtractedPage, SearchHit

logger = logging.getLogger(__name__)


class SearchSession:
    """Cache search, page extraction, and crawl calls within one CLI run.

    The cache is deliberately keyed by the full execution shape (query, engines,
    result count, URL, crawl depth, etc.) so it is safe to reuse between the
    three parallel agents and the later review phase.
    """

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._inflight: set[str] = set()
        self._search_cache = self._load_json("search_cache.json")
        self._page_cache = self._load_json("page_cache.json")
        self._crawl_cache = self._load_json("crawl_cache.json")

    def search(
        self,
        query: str,
        *,
        engines: list[str] | tuple[str, ...] = pool.DEFAULT_SEARCH_ENGINES,
        num_per_engine: int = 8,
        exclude_domains: tuple[str, ...] = pool.DEFAULT_EXCLUDE_DOMAINS,
        log_context: str = "",
    ) -> list[SearchHit]:
        key = self._cache_key({
            "kind": "search",
            "query": query,
            "engines": list(engines),
            "num_per_engine": num_per_engine,
            "exclude_domains": list(exclude_domains),
        })
        cached = self._get_or_mark(self._search_cache, key, log_context, "search")
        if cached is not None:
            return [SearchHit(**item) for item in cached]
        try:
            hits = pool.search(
                query,
                engines=engines,
                num_per_engine=num_per_engine,
                exclude_domains=exclude_domains,
                log_context=log_context,
            )
            payload = [asdict(hit) for hit in hits]
            self._store(self._search_cache, key, payload, "search_cache.json")
            return hits
        finally:
            self._unmark(key)

    def read_url(self, url: str, *, log_context: str = "") -> ExtractedPage:
        key = self._cache_key({"kind": "read", "url": url})
        cached = self._get_or_mark(self._page_cache, key, log_context, "read")
        if cached is not None:
            return ExtractedPage(**cached)
        try:
            page = pool.read_url(url, log_context=log_context)
            self._store(self._page_cache, key, asdict(page), "page_cache.json")
            return page
        finally:
            self._unmark(key)

    def crawl_url(
        self,
        url: str,
        *,
        max_depth: int = 1,
        limit: int = 4,
        log_context: str = "",
    ) -> list[ExtractedPage]:
        key = self._cache_key({
            "kind": "crawl",
            "url": url,
            "max_depth": max_depth,
            "limit": limit,
        })
        cached = self._get_or_mark(self._crawl_cache, key, log_context, "crawl")
        if cached is not None:
            return [ExtractedPage(**item) for item in cached]
        try:
            pages = pool.crawl_url(
                url,
                max_depth=max_depth,
                limit=limit,
                log_context=log_context,
            )
            self._store(self._crawl_cache, key, [asdict(page) for page in pages], "crawl_cache.json")
            return pages
        finally:
            self._unmark(key)

    def _get_or_mark(
        self,
        cache: dict[str, Any],
        key: str,
        log_context: str,
        label: str,
    ) -> Any | None:
        ctx = f"{log_context} " if log_context else ""
        with self._cond:
            while key in self._inflight:
                logger.info("%s%s CACHE WAIT key=%s", ctx, label, key[:96])
                self._cond.wait()
            if key in cache:
                logger.info("%s%s CACHE HIT key=%s", ctx, label, key[:96])
                return cache[key]
            self._inflight.add(key)
            return None

    def _store(self, cache: dict[str, Any], key: str, value: Any, filename: str) -> None:
        with self._lock:
            cache[key] = value
            self._write_json(filename, cache)

    def _unmark(self, key: str) -> None:
        with self._cond:
            self._inflight.discard(key)
            self._cond.notify_all()

    def _load_json(self, filename: str) -> dict[str, Any]:
        if not self.cache_dir:
            return {}
        path = self.cache_dir / filename
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception as exc:  # noqa: BLE001
            logger.info("search session cache ignored path=%s error=%s", path, exc)
            return {}

    def _write_json(self, filename: str, data: dict[str, Any]) -> None:
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / filename
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _cache_key(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).lower()
