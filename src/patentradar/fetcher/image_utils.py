"""图片归一化：统一压到长边 1024 + 转 PNG，给下游 vision LLM。

各 fetcher（HTML / PDF）抓到原始字节后都过这里，确保发给 LLM 的图大小一致、
token 成本可预测（一张 1024 长边的 PNG ≈ 1500-2500 vision tokens，是 4K 原图
的 1/4 左右，对结构/标注图判读完全够用）。
"""

from __future__ import annotations

import hashlib
import logging
from io import BytesIO

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
    try:
        with Image.open(BytesIO(raw)) as im:
            im = im.convert("RGB")
            w, h = im.size
            long_edge = max(w, h)
            if long_edge > max_edge:
                ratio = max_edge / long_edge
                im = im.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many things
        logger.info("normalize_png failed: %s", exc)
        return None


def png_hash(png: bytes) -> str:
    """图片去重用的内容指纹：sha256 前 16 hex 字符就足以区分图集里的图。"""
    return hashlib.sha256(png).hexdigest()[:16]
