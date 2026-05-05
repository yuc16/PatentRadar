"""把 FinalReport / 上游产物渲染为 Markdown（PRD §14 结构）。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..schemas import (
    AgentOutput,
    FinalCandidate,
    FinalReport,
    TaskPackage,
)

_SH = ZoneInfo("Asia/Shanghai")
_DISCLAIMER = (
    '> ⚠️ 本报告仅基于公开资料进行专利侵权线索辅助分析，'
    '不构成法律意见或正式侵权结论；'
    '所有"可能满足"判断需经人工复核。'
)


def render_markdown(
    *,
    task: TaskPackage,
    agent_outputs: list[AgentOutput],
    final: FinalReport,
) -> str:
    """渲染 PRD §14 结构的 Markdown 报告。"""
    parts: list[str] = []
    parts.append(f"# 专利竞品侵权线索挖掘报告 — {task.patent.publication_no}")
    parts.append("")
    parts.append(_DISCLAIMER)
    parts.append("")
    parts.append("---")
    parts.append("")

    # 1. 任务概述
    parts.append("## 1. 任务概述")
    parts.append("")
    parts.append(f"- **专利公开号**：{task.patent.publication_no}")
    parts.append(f"- **专利名称**：{task.patent.title or '(未知)'}")
    parts.append(f"- **专利权人**：{', '.join(task.patent.assignees) or '(未知)'}")
    parts.append(f"- **申请日**：{task.patent.application_date or '(未知)'}")
    parts.append(f"- **发明人**：{', '.join(task.patent.inventors) or '(未知)'}")
    parts.append(f"- **数据来源**：[Google Patents]({task.patent.source_url})")
    parts.append(f"- **检索目标**：围绕权利要求 1 挖掘可能落入其技术特征范围的公开竞品 Top5")
    parts.append(
        f"- **报告生成时间**：{datetime.now(_SH).isoformat(timespec='seconds')}"
    )
    parts.append(f"- **复核模型**：{final.reviewer_model}（耗时 {final.elapsed_seconds}s）")
    parts.append("")

    # 2. 权利要求 1 拆解
    parts.append("## 2. 权利要求 1 拆解")
    parts.append("")
    parts.append("**权利要求 1 原文**：")
    parts.append("")
    parts.append("```")
    parts.append(task.claim_1_text)
    parts.append("```")
    parts.append("")
    parts.append("| 编号 | 技术特征原文 | 工程术语 | 必要 |")
    parts.append("|---|---|---|:---:|")
    for f in task.claim_features:
        terms = "、".join(f.engineering_terms[:6]) or "—"
        text = _md_escape(f.feature_text)
        parts.append(f"| {f.feature_id} | {text} | {terms} | {'✓' if f.is_essential else ''} |")
    parts.append("")

    # 3. 多 Agent 检索概览
    parts.append("## 3. 多 Agent 检索概览")
    parts.append("")
    parts.append(
        "| Agent | 视角 | 模型 | 耗时(s) | queries | Top 候选 | 已丢弃 |"
    )
    parts.append("|---|---|---|---:|---:|---:|---:|")
    for ao in agent_outputs:
        parts.append(
            f"| {ao.agent_name} | {ao.search_perspective} | "
            f"{ao.llm_model or '?'} | {ao.elapsed_seconds or '?'} | "
            f"{len(ao.queries_used)} | {len(ao.top5_candidates)} | "
            f"{len(ao.discarded_candidates)} |"
        )
    parts.append("")

    # 4. 候选竞品去重汇总
    parts.append("## 4. 候选竞品合并去重汇总")
    parts.append("")
    n_raw = sum(len(o.top5_candidates) for o in agent_outputs)
    n_top = len(final.top5)
    n_excl = len(final.excluded)
    n_need = len(final.needs_manual_review)
    parts.append(f"- 三 Agent 合并前候选总数：**{n_raw}**")
    parts.append(f"- GPT-5.5 复核后保留 Top：**{n_top}**")
    parts.append(f"- 合并 / 排除 / 转人工复查：剩余 {n_raw - n_top} 个 → 排除 {n_excl}，转人工 {n_need}")
    multi_alias = [c for c in final.top5 if len(c.aliases) >= 2]
    if multi_alias:
        parts.append("- 跨 Agent 合并的候选（含 ≥2 个别名）：")
        for c in multi_alias:
            parts.append(
                f"  - {c.candidate_id} {c.company}（别名: {', '.join(c.aliases[:6])}）"
            )
    parts.append("")

    # 5. 最终 Top5 候选竞品
    parts.append("## 5. 最终 Top5 候选竞品")
    parts.append("")
    if not final.top5:
        parts.append("> 无合格候选（宁缺毋滥，PRD §9.2）。")
    else:
        parts.append(
            "| 排名 | 公司 | 产品 / 型号 | 上市/发布/量产日期 | 分数 | 风险等级 | 主要证据数 | 主要缺口 |"
        )
        parts.append("|---:|---|---|---|---:|---|---:|---|")
        for c in final.top5:
            gaps = "、".join(g.get("feature_id", "") for g in c.remaining_gaps)
            parts.append(
                f"| {c.rank} | {c.company} | {c.product[:50]} | "
                f"{c.product_launch_date or '待核查'} | "
                f"{c.score:.1f} | {c.risk_level} | "
                f"{len(c.main_evidence_urls)} | {gaps or '—'} |"
            )
    parts.append("")

    # 6. Top5 逐项权利特征对比表
    parts.append("## 6. Top5 逐项权利特征对比表")
    parts.append("")
    for c in final.top5:
        parts.append(f"### {c.rank}. {c.company} — {c.product}")
        parts.append("")
        if c.aliases:
            parts.append(f"**别名**：{', '.join(c.aliases)}")
            parts.append("")
        parts.append(f"**上市/发布/量产日期**：{c.product_launch_date or '待核查'}")
        if c.product_launch_date_evidence_url:
            parts.append(f"**日期证据**：{c.product_launch_date_evidence_url}")
        parts.append("")
        parts.append(f"**最终分数**：{c.score:.1f}　**风险等级**：{c.risk_level}")
        parts.append("")
        if c.reason_for_top5:
            parts.append(f"**入选理由**：{c.reason_for_top5}")
            parts.append("")
        parts.append("| 特征 | 判断 | 推理 | 主要证据 |")
        parts.append("|:---:|:---:|---|---|")
        for fm in c.final_feature_table:
            ev_links = " / ".join(
                f"[{_short_title(ev.title or ev.url)}]({ev.url})"
                for ev in fm.evidence[:3]
                if ev.url
            )
            reasoning = _md_escape(fm.reasoning[:200] + ("…" if len(fm.reasoning) > 200 else ""))
            parts.append(
                f"| {fm.feature_id} | {fm.judgement} | "
                f"{reasoning or '—'} | {ev_links or '—'} |"
            )
        parts.append("")
        if c.remaining_gaps:
            parts.append("**剩余缺口**：")
            for g in c.remaining_gaps:
                parts.append(f"- {g.get('feature_id', '?')}: {g.get('gap', '')}")
            parts.append("")

    # 7. 被排除候选及原因
    parts.append("## 7. 被排除候选及原因")
    parts.append("")
    if final.excluded:
        parts.append("| 公司 | 产品 | 排除原因 |")
        parts.append("|---|---|---|")
        for x in final.excluded:
            parts.append(
                f"| {x.company or '—'} | {x.product or '—'} | "
                f"{_md_escape(x.discard_reason)} |"
            )
    else:
        parts.append("> GPT-5.5 复核阶段未追加排除（先前 Agent 阶段已按硬规则过滤）。")
    parts.append("")

    # 8. 证据不足但值得人工复查的线索
    parts.append("## 8. 证据不足但值得人工复查的线索")
    parts.append("")
    if final.needs_manual_review:
        parts.append("| 候选 | 公司 / 产品 | 缺口 | 建议检索方向 |")
        parts.append("|---|---|---|---|")
        for n in final.needs_manual_review:
            parts.append(
                f"| {n.candidate_id} | {n.company} / {n.product} | "
                f"{_md_escape(n.gap)} | {_md_escape(n.suggested_search_direction)} |"
            )
    else:
        parts.append("> 无需要人工补查的候选。")
    parts.append("")

    # 9. 结论与后续建议
    parts.append("## 9. 结论与后续建议")
    parts.append("")
    high = [c for c in final.top5 if c.risk_level == "高度疑似落入"]
    mid = [c for c in final.top5 if c.risk_level == "中度疑似"]
    if high:
        parts.append(f"- **高优先级（高度疑似落入）{len(high)} 个**：")
        for c in high:
            parts.append(f"  - {c.company} / {c.product}（{c.score:.1f}）")
    if mid:
        parts.append(f"- **次优先级（中度疑似）{len(mid)} 个**：")
        for c in mid:
            parts.append(f"  - {c.company} / {c.product}（{c.score:.1f}）")
    if not high and not mid:
        parts.append(
            '- **本次未发现"高度疑似落入"或"中度疑似"候选**，'
            'Top5 均处于"局部相似"或"弱相关"档位；'
            '建议先按系统标记的"人工复查方向"补充资料后再判断。'
        )
    if final.notes:
        parts.append("")
        parts.append(f"**复核备注**：{final.notes}")
    parts.append("")
    parts.append("**通用建议**：")
    parts.append(
        '1. 对 Top5 中"可能满足"判断逐条复核 reasoning，验证推理链是否成立；'
    )
    parts.append(
        "2. 联系 §8 中标注的人工复查候选，按建议检索方向继续找官方 PDF / 数据手册 / 拆解报告；"
    )
    parts.append("3. 必要时引入专利代理人 / 律师做正式 FTO 与侵权对比分析。")
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(_DISCLAIMER)
    parts.append("")

    return "\n".join(parts)


def _md_escape(text: str) -> str:
    """Markdown 表格里 | 与换行的简单转义。"""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _short_title(s: str) -> str:
    s = (s or "").strip()
    if len(s) > 36:
        s = s[:33] + "…"
    return s or "证据"
