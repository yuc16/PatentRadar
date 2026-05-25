"""图片归一化：统一压到长边 1024 + 转 PNG，给下游 vision LLM。

各 fetcher（HTML / PDF）抓到原始字节后都过这里，确保发给 LLM 的图大小一致、
token 成本可预测（一张 1024 长边的 PNG ≈ 1500-2500 vision tokens，是 4K 原图
的 1/4 左右，对结构/标注图判读完全够用）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

# 1024 长边是 vision 模型判读结构图/规格表的甜点：再大也看不到额外细节，
# 再小（512）会丢小字标注。
DEFAULT_MAX_EDGE = 1024


def normalize_png(raw: bytes, *, max_edge: int = DEFAULT_MAX_EDGE) -> bytes | None:
    """把任意图片字节流统一成 PNG 且长边 ≤ max_edge。

    失败（损坏 / 不支持格式）返回 None。
    """
    try:
        from PIL import Image  # noqa: WPS433 - lazy import
    except ImportError as exc:
        logger.warning("Pillow not available, skip image normalize: %s", exc)
        return None
    converted = None
    resized = None
    try:
        # 原 image 由 with 管理；convert()/resize() 产物是新 Image 实例，with
        # 不会管它们，手动 close 避免 Pillow 文件描述符 / 解码缓冲累积。
        with Image.open(BytesIO(raw)) as im:
            converted = im.convert("RGB")
        w, h = converted.size
        long_edge = max(w, h)
        target = converted
        if long_edge > max_edge:
            ratio = max_edge / long_edge
            resized = converted.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            target = resized
        buf = BytesIO()
        target.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many things
        logger.info("normalize_png failed: %s", exc)
        return None
    finally:
        if resized is not None:
            resized.close()
        if converted is not None:
            converted.close()


def png_hash(png: bytes) -> str:
    """图片去重用的内容指纹：sha256 前 16 hex 字符就足以区分图集里的图。"""
    return hashlib.sha256(png).hexdigest()[:16]


def dump_visual_log(
    visual_log_dir: Path,
    candidate_id: str,
    fetched_images: list[dict],
) -> None:
    """把候选的图集合落盘为 manifest.json + 各图 PNG，供事后审计。

    调用方约定两类目录：
    - `visual_log_fetched/<cid>/`：fetcher 抓回来的全集（pipeline 端 dump）
    - `visual_log_sent/<cid>/`：worker dedup + cap 后实际送 LLM 的子集
    """
    if not fetched_images:
        return
    cand_dir = visual_log_dir / candidate_id
    cand_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for idx, img in enumerate(fetched_images):
        png = img.get("png")
        if not isinstance(png, (bytes, bytearray)):
            continue
        png_bytes = bytes(png)
        h = png_hash(png_bytes)
        filename = f"img_{idx:02d}_{h}.png"
        (cand_dir / filename).write_bytes(png_bytes)
        manifest.append({
            "index": idx,
            "filename": filename,
            "src_url": img.get("url", ""),
            "alt_or_title": img.get("title", ""),
            "size_bytes": len(png_bytes),
            "sha256_prefix": h,
            "score": img.get("score", 0),
            # surrounding_text = 图所在 HTML 上下文（figcaption + 前后段落首句）
            # 或 PDF 同页文本头部，最多 300 字符——审计 LLM 看图时实际拿到的文字线索
            "surrounding_text": (img.get("surrounding_text") or "")[:300],
        })
    (cand_dir / "manifest.json").write_text(
        json.dumps({"candidate_id": candidate_id, "images": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
