"""上下文动态压缩（PRD §17.4 成本控制 / 上下文长度管理）。

策略：
1. **token 估算**：中文 1 char ≈ 1.8 token、英文 1 char ≈ 0.4 token（保守上界）。
2. **预算计算**：``budget = ctx_window * COMPACTOR_BUDGET_RATIO - COMPACTOR_OUTPUT_RESERVE - fixed_overhead``。
3. **三级压缩**：
   a) 整体 ≤ 预算 → 全量保留；
   b) 整体超出 → 对**单篇 > 阈值**的长文调用便宜 LLM 做关键事实摘要（300~500 tokens）；
   c) 仍超出 → 按 token 数从大到小迭代腰斩（保留前后段），最后实在不够才丢弃。

每次返回元信息（summarized / truncated / dropped 数 + 最终 token 总数），便于 logger 观察。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from . import config
from .llm.client import chat_text
from .search.base import ExtractedPage

logger = logging.getLogger("patentradar.compactor")

_CN_RE = re.compile(r"[一-鿿]")
_FULL_TEXT_CHAR_LIMIT = 12_000
_EXCERPT_CHAR_LIMIT = 8_000
_EVIDENCE_KEYWORDS = (
    "型号", "产品", "规格", "规格书", "参数", "尺寸", "长度", "宽度", "厚度", "高度",
    "表面积", "体积", "容量", "电压", "电流", "能量密度", "质量", "重量", "壳体",
    "极柱", "极耳", "结构", "连接", "mm", "cm", "ah", "wh", "kwh",
    "model", "product", "specification", "datasheet", "parameter", "dimension",
    "length", "width", "thickness", "height", "capacity", "voltage", "current",
    "energy density", "weight", "mass", "terminal", "tab", "structure",
)


def count_tokens(text: str) -> int:
    """简易 token 估算（中英文混合保守值）。"""
    if not text:
        return 0
    cn = len(_CN_RE.findall(text))
    other = max(0, len(text) - cn)
    return int(cn * 1.8 + other * 0.4)


_SUMMARIZE_SYS = """你是技术资料压缩助手。把给定网页 / PDF 抽取的正文压缩为**关键事实摘要**，用于专利侵权特征比对。

【输出要求】
- 长度 200~400 字（约 300~500 tokens）。
- 用要点格式，每行 1 条事实，行与行用 `\\n` 分隔。
- 重点保留：产品名 / 型号、公司、技术参数、结构描述（部件 / 连接 / 材料 / 工艺）、算法 / 公式、应用场景、是否在中国市场销售。
- 删去：广告 / 营销修辞、其他无关产品、联系方式、网站导航、其他领域内容。
- 必须基于原文，不得编造或外推。
- 直接输出摘要，不要"以下是摘要"、不要 Markdown 标题。
"""


def summarize(text: str, *, context: str = "", target_tokens: int = 400) -> str:
    """调用便宜 LLM 把长文压缩为关键事实摘要。"""
    ep = config.get_compactor_endpoint()
    user_parts: list[str] = []
    if context:
        user_parts.append(f"【聚焦上下文（用于判断哪些信息相关）】\n{context}\n")
    # 摘要源文本同样有上限，避免输入端就爆
    src = text if len(text) < 30_000 else text[:15_000] + "\n…[原文中段省略]…\n" + text[-15_000:]
    user_parts.append(f"【正文】\n{src}\n")
    user_parts.append(f"请输出 ~{target_tokens} token 的关键事实摘要。")
    try:
        out = chat_text(
            ep,
            system=_SUMMARIZE_SYS,
            user="\n".join(user_parts),
            temperature=0.1,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("摘要失败 (fallback 截断): %s", exc)
        return text[:1500] + "…[摘要失败，截断]"
    return out.strip()


@dataclass
class PackInfo:
    total_tokens: int
    budget_tokens: int
    fixed_overhead_tokens: int
    excerpted_count: int = 0
    summarized_count: int = 0
    truncated_count: int = 0
    dropped_count: int = 0


def pack_evidence(
    pages: list[ExtractedPage],
    *,
    ctx_window: int,
    fixed_overhead_chars: int,
    summary_context: str = "",
    enable_summarize: bool = True,
) -> tuple[list[ExtractedPage], PackInfo]:
    """按上下文预算压缩 evidence 列表。

    Args:
        pages: 抽取后的网页正文列表（会被深拷贝替换）。
        ctx_window: 该次调用的目标 LLM 的上下文窗口（tokens）。
        fixed_overhead_chars: 除 evidence 外，prompt 其它部分的字符数（用于扣减预算）。
        summary_context: 给摘要 LLM 看的聚焦上下文（如权要 1 + 候选公司 + 技术特征列表）。
        enable_summarize: 关闭后只走截断，不调用 LLM 摘要（用于 LLM 不可用时降级）。
    """
    budget = int(ctx_window * config.COMPACTOR_BUDGET_RATIO) - config.COMPACTOR_OUTPUT_RESERVE
    fixed_tokens = count_tokens("." * fixed_overhead_chars)
    evidence_budget = max(2000, budget - fixed_tokens)

    out_pages: list[ExtractedPage] = [
        ExtractedPage(url=p.url, title=p.title, text=p.text or "", source=p.source, raw=p.raw)
        for p in pages
    ]
    excerpted_count = 0
    for i, p in enumerate(out_pages):
        if len(p.text) <= _FULL_TEXT_CHAR_LIMIT:
            continue
        excerpt = _focused_excerpt(p.text, context=summary_context)
        if excerpt != p.text:
            out_pages[i] = ExtractedPage(
                url=p.url,
                title=p.title,
                text=excerpt,
                source=f"{p.source}+excerpt",
                raw=p.raw,
            )
            excerpted_count += 1
    page_tokens = [count_tokens(p.text) for p in out_pages]
    total = sum(page_tokens)
    info = PackInfo(
        total_tokens=total,
        budget_tokens=evidence_budget,
        fixed_overhead_tokens=fixed_tokens,
        excerpted_count=excerpted_count,
    )

    if total <= evidence_budget:
        return out_pages, info

    # —— 第一级：长文 → LLM 摘要 ——
    if enable_summarize and out_pages:
        single_max = max(2000, evidence_budget // len(out_pages) * 2)
        for i, p in enumerate(out_pages):
            if page_tokens[i] > single_max:
                target = max(300, min(single_max // 2, 600))
                logger.info(
                    "compactor 摘要 [%s] (%d → ~%d tokens)",
                    p.url[:60], page_tokens[i], target,
                )
                summary = summarize(p.text, context=summary_context, target_tokens=target)
                out_pages[i] = ExtractedPage(
                    url=p.url, title=p.title, text=summary,
                    source=f"{p.source}+summary", raw=p.raw,
                )
                page_tokens[i] = count_tokens(summary)
                info.summarized_count += 1
        total = sum(page_tokens)
        info.total_tokens = total

    # —— 第二级：仍超 → 腰斩截断 ——
    while total > evidence_budget and out_pages:
        idx = max(range(len(out_pages)), key=lambda i: page_tokens[i])
        text = out_pages[idx].text or ""
        if len(text) > 600:
            half = len(text) // 4
            new_text = text[:half] + "\n…[中段已截断]…\n" + text[-half:]
            out_pages[idx] = ExtractedPage(
                url=out_pages[idx].url,
                title=out_pages[idx].title,
                text=new_text,
                source=out_pages[idx].source + "+truncated",
                raw=out_pages[idx].raw,
            )
            page_tokens[idx] = count_tokens(new_text)
            info.truncated_count += 1
        else:
            # 太短了，宁可整段丢
            out_pages.pop(idx)
            page_tokens.pop(idx)
            info.dropped_count += 1
        total = sum(page_tokens)
        info.total_tokens = total

    return out_pages, info


def _focused_excerpt(text: str, *, context: str = "") -> str:
    """Keep dense technical evidence from long extracted pages before LLM matching."""
    if len(text) <= _FULL_TEXT_CHAR_LIMIT:
        return text
    keywords = set(_EVIDENCE_KEYWORDS)
    for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9+_.-]{1,}|[\u4e00-\u9fff]{2,}", context.lower()):
        if len(term) >= 2:
            keywords.add(term)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chosen: list[str] = []
    seen: set[int] = set()
    for idx, line in enumerate(lines):
        low = line.lower()
        has_keyword = any(k in low for k in keywords)
        has_parameter = bool(re.search(r"\b\d+(?:\.\d+)?\s?(?:mm|cm|ah|wh|kwh|v|a|kg|g)\b", low))
        if not has_keyword and not has_parameter:
            continue
        for j in range(max(0, idx - 1), min(len(lines), idx + 2)):
            if j not in seen:
                chosen.append(lines[j])
                seen.add(j)
        if sum(len(x) for x in chosen) >= _EXCERPT_CHAR_LIMIT:
            break

    if not chosen:
        return text[: _EXCERPT_CHAR_LIMIT // 2] + "\n...[长文中段已省略]...\n" + text[-_EXCERPT_CHAR_LIMIT // 2 :]

    body = "\n".join(chosen)
    if len(body) > _EXCERPT_CHAR_LIMIT:
        body = body[:_EXCERPT_CHAR_LIMIT]
    return (
        "[长文已按权利要求和技术参数聚焦摘录；原文过长，未全文送入 Agent]\n"
        + body
    )
