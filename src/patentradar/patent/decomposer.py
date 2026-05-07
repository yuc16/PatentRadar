"""权利要求 1 拆解（GPT-5.5）。

- 无公式 → 纯文本路径：仅传 HTML 抽取的草稿，不附图。
- 有公式残缺 → 多模态路径：附 PDF 权要书页面 PNG，让 GPT-5.5 用 LaTeX 还原。

两条路径共用同一个系统提示与输出 schema。
"""

from __future__ import annotations

from typing import Any

from .. import prompts
from ..llm import codex
from ..schemas import ClaimFeature
from ..search import cn_industry


def decompose(
    *,
    pub_no: str,
    title: str | None,
    claim_1_html: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    reasoning_effort: str = "medium",
) -> tuple[str, list[ClaimFeature], str | None]:
    """返回 (最终版 claim_1_text, 特征列表, industry_tag)。

    ``industry_tag`` 的合法取值由 ``data/cn_industry_sites/*.json`` 自动派生
    （见 ``cn_industry.valid_tags()``）。新增领域只需新建 JSON，无需改代码或 prompt。
    images 为空 → 纯文本拆解；非空 → 多模态拆解（公式以 LaTeX 还原）。
    """
    system = (
        prompts.load("claim_decompose_system")
        .replace("<<INDUSTRY_TAG_TABLE>>", cn_industry.render_industry_tag_table_for_prompt())
        .replace("<<INDUSTRY_TAG_OR_LIST>>", cn_industry.render_industry_tag_or_list())
    )
    if images:
        user = prompts.render(
            "claim_decompose_user_with_vision",
            pub_no=pub_no,
            title=title or "(未知)",
            claim_1_html=claim_1_html,
            n_images=len(images),
        )
    else:
        user = prompts.render(
            "claim_decompose_user_text_only",
            pub_no=pub_no,
            title=title or "(未知)",
            claim_1_html=claim_1_html,
        )

    payload = codex.chat_json(
        system=system,
        user_text=user,
        images=images or None,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
    )
    return _parse_payload(payload)


# 兼容旧导入
def decompose_with_vision(
    *,
    pub_no: str,
    title: str | None,
    claim_1_html: str,
    images: list[bytes],
    model: str | None = None,
    reasoning_effort: str = "medium",
) -> tuple[str, list[ClaimFeature], str | None]:
    return decompose(
        pub_no=pub_no,
        title=title,
        claim_1_html=claim_1_html,
        images=images,
        model=model,
        reasoning_effort=reasoning_effort,
    )


def _parse_payload(
    payload: dict[str, Any],
) -> tuple[str, list[ClaimFeature], str | None]:
    claim_1_text = str(payload.get("claim_1_text") or "").strip()
    if not claim_1_text:
        raise RuntimeError(f"GPT-5.5 未返回 claim_1_text: {payload!r}")

    raw_feats = payload.get("claim_features") or []
    if not isinstance(raw_feats, list) or not raw_feats:
        raise RuntimeError(f"GPT-5.5 未返回 claim_features: {payload!r}")

    features: list[ClaimFeature] = []
    for i, item in enumerate(raw_feats, start=1):
        if not isinstance(item, dict):
            continue
        fid = str(item.get("feature_id") or f"F{i}").strip()
        ftext = str(item.get("feature_text") or "").strip()
        if not ftext:
            continue
        terms = item.get("engineering_terms") or []
        if not isinstance(terms, list):
            terms = []
        mkts = item.get("marketing_terms") or []
        if not isinstance(mkts, list):
            mkts = []
        notes_val = item.get("notes")
        notes = str(notes_val).strip() if notes_val else ""
        features.append(
            ClaimFeature(
                feature_id=fid,
                feature_text=ftext,
                engineering_terms=[str(t).strip() for t in terms if str(t).strip()],
                marketing_terms=[str(t).strip() for t in mkts if str(t).strip()],
                is_essential=bool(item.get("is_essential", True)),
                notes=notes or None,
            )
        )
    if not features:
        raise RuntimeError("GPT-5.5 返回的 claim_features 解析后为空")

    raw_tag = payload.get("industry_tag")
    industry_tag: str | None = None
    if raw_tag:
        candidate = str(raw_tag).strip().lower()
        if candidate in cn_industry.valid_tags():
            industry_tag = candidate

    return claim_1_text, features, industry_tag
