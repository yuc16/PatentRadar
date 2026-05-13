"""基于现有 visual_log/<cid>/manifest.json，对每张图按 alt/title 跑新过滤规则，
显示哪些会被滤掉、哪些保留。

不重新下载图，不重判 LLM，纯文本规则演练 — 用来评估新黑名单是否过滤合理。

注：score 阈值（>=2）需要原始 HTML 才能重现，dry-run 跑不出来；只能跑：
  - alt 黑名单
  - alt 信息量门槛（纯数字 / 过短 / 文件扩展名结尾）

Usage:
  python tests/competitor_search/dryrun_visual_filter.py \
    tests/cross_llm_eval/CN105335144B/codex_tier1only/module_two/visual_log/P02/manifest.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from patentradar.fetcher.web_fetcher import _is_noisy_alt


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    manifest_path = Path(sys.argv[1])
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = data.get("images", [])
    kept: list[dict] = []
    dropped: list[tuple[dict, str]] = []
    for img in images:
        alt = img.get("alt_or_title", "")
        if _is_noisy_alt(alt):
            dropped.append((img, "alt 黑名单/信息量不足"))
            continue
        kept.append(img)
    total = len(images)
    print(f"\n=== {manifest_path} ===")
    print(f"原始: {total} 张 → 保留: {len(kept)} | 过滤: {len(dropped)}")
    print(f"过滤率: {len(dropped)/total*100:.1f}%\n")

    print("--- 保留 ---")
    for img in kept:
        print(f"  [{img['index']:02d}] {(img.get('alt_or_title') or '(no alt)')[:70]}")
        print(f"        {img['src_url']}")
    print("\n--- 过滤掉 ---")
    for img, reason in dropped:
        print(f"  [{img['index']:02d}] {reason}: {(img.get('alt_or_title') or '(no alt)')[:70]}")


if __name__ == "__main__":
    main()
