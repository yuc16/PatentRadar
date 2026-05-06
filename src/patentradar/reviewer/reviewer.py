"""GPT-5.5 最终复核（PRD §11）。

接收三个 Agent 的原始输出（list[AgentOutput]）+ task_package，平铺所有候选 +
其完整证据，让 GPT-5.5 在一次调用中完成：
  1. 跨候选合并去重（同公司不同名 / 同产品不同型号）
  2. 证据真实性校验
  3. 重新打分 + 风险等级判定
  4. 输出 Top5 + 排除清单 + 人工复查清单

不再依赖代码层的 token 归一化合并 —— 由 GPT-5.5 自己判断同义。
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
from pathlib import Path
from typing import Any

from .. import evidence as evidence_strategy, prompts, scoring
from ..agents.base import _normalize_reliability, _normalize_source_type
from ..dates import normalize_date_string
from ..llm import codex
from ..schemas import (
    AgentOutput,
    Candidate,
    Evidence,
    FeatureMatch,
    FinalCandidate,
    FinalReport,
    NeedsManualReview,
    ReviewExcluded,
    TaskPackage,
)
from ..search import pool

logger = logging.getLogger("patentradar.reviewer")


REVIEW_SUPPLEMENT_MAX_CANDIDATES = 15
REVIEW_SUPPLEMENT_FEATURES_PER_CANDIDATE = 4
REVIEW_SUPPLEMENT_TARGETS_PER_CANDIDATE = 3
REVIEW_SUPPLEMENT_QUERIES_PER_TARGET = 2
REVIEW_SUPPLEMENT_HITS_PER_FEATURE = 3
REVIEW_SUPPLEMENT_SUMMARY_CHARS = 1000
REVIEW_SUPPLEMENT_ENGINES = pool.DEFAULT_SEARCH_ENGINES


def _format_features_block(task: TaskPackage) -> str:
    return "\n".join(
        f"- {f.feature_id} (essential={f.is_essential}): {f.feature_text}"
        for f in task.claim_features
    )


def _format_one_candidate(agent_name: str, idx: int, c: Candidate) -> str:
    """把单个 Agent Top 候选格式化为给 GPT-5.5 看的文本块。"""
    parts = [f"━━━ raw_id={agent_name}#{idx}  来源 Agent: {agent_name} ━━━"]
    parts.append(f"公司: {c.company}")
    parts.append(f"产品: {c.product}")
    if c.aliases:
        parts.append(f"别名: {', '.join(c.aliases)}")
    if c.product_launch_date:
        parts.append(
            f"公开上市/发布/量产日期: {c.product_launch_date}"
            + (
                f"（证据: {c.product_launch_date_evidence_url}）"
                if c.product_launch_date_evidence_url else ""
            )
        )
    parts.append(f"该 Agent 给出的初步分数: {c.score}")
    if c.reason_for_top5:
        parts.append(f"该 Agent 入选理由: {c.reason_for_top5[:200]}")

    parts.append("\n[证据]")
    seen_urls: set[str] = set()
    for fm in c.feature_match_table:
        for ev in fm.evidence:
            if not ev.url or ev.url in seen_urls:
                continue
            seen_urls.add(ev.url)
            tier = evidence_strategy.tier_label(ev.url, ev.title)
            parts.append(
                f"  • 来源类型={ev.source_type}({ev.source_reliability}) / {tier}"
            )
            parts.append(f"    URL: {ev.url}")
            parts.append(f"    标题: {ev.title}")
            if ev.summary:
                parts.append(f"    摘要: {ev.summary[:300]}")
            if ev.supported_features:
                parts.append(f"    支撑特征: {', '.join(ev.supported_features)}")
    if not seen_urls:
        parts.append("  (无证据)")

    parts.append("\n[该 Agent 的特征判断]")
    for fm in c.feature_match_table:
        ev_count = len([e for e in fm.evidence if e.url])
        rea = (fm.reasoning or "").replace("\n", " ")
        if len(rea) > 180:
            rea = rea[:180] + "…"
        parts.append(f"  {fm.feature_id}: {fm.judgement}({fm.score}) ev={ev_count}  推理: {rea}")
    parts.append("")
    return "\n".join(parts)


def _format_candidates_block(agent_outputs: list[AgentOutput]) -> tuple[str, int]:
    blocks: list[str] = []
    n = 0
    for ao in agent_outputs:
        for i, c in enumerate(ao.top5_candidates, start=1):
            blocks.append(_format_one_candidate(ao.agent_name, i, c))
            n += 1
    return "\n".join(blocks), n


def _candidate_key(company: str, product: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", f"{company}{product}".lower())


def _lookup_launch_date(
    launch_lookup: dict[str, tuple[str | None, str | None]],
    company: str,
    product: str,
) -> tuple[str | None, str | None]:
    key = _candidate_key(company, product)
    if key in launch_lookup:
        return launch_lookup[key]
    for raw_key, value in launch_lookup.items():
        if key and raw_key and (key in raw_key or raw_key in key):
            return value
    return None, None


def review_agent_outputs(
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
    *,
    reasoning_effort: str = "medium",
    supplement_cache_path: str | Path | None = None,
) -> FinalReport:
    """主入口：直接接收三 Agent 输出，平铺给 GPT-5.5。"""
    t0 = time.monotonic()
    model = (os.getenv("REVIEWER_MODEL") or "gpt-5.5").strip()

    cache_file = Path(supplement_cache_path) if supplement_cache_path else None
    cached = _load_supplement_cache(cache_file, task) if cache_file else None
    if cached is not None:
        agent_outputs, supplement_count = cached
    else:
        agent_outputs, supplement_count = _supplement_agent_outputs(agent_outputs, task)
        if cache_file:
            _write_supplement_cache(cache_file, agent_outputs, task, supplement_count)
    candidates_block, n_candidates = _format_candidates_block(agent_outputs)

    system = prompts.load("reviewer_system")
    user = prompts.render(
        "reviewer_user",
        pub_no=task.patent.publication_no,
        title=task.patent.title or "(未知)",
        assignees=", ".join(task.patent.assignees) or "(未知)",
        application_date=task.patent.application_date or "(未知)",
        claim_1_text=task.claim_1_text,
        features_block=_format_features_block(task),
        n_candidates=n_candidates,
        candidates_block=candidates_block,
    )

    logger.info(
        "[reviewer] GPT-5.5 review START candidates=%d supplement_urls=%d",
        n_candidates, supplement_count,
    )
    t_review = time.monotonic()
    payload = _chat_json_with_retries(
        system=system,
        user_text=user,
        model=model,
        reasoning_effort=reasoning_effort,
        verbosity="medium",
    )
    logger.info("[reviewer] GPT-5.5 review DONE elapsed=%.2fs", time.monotonic() - t_review)

    feature_text_by_id = {f.feature_id: f.feature_text for f in task.claim_features}

    # 收集所有原始 evidence URL，用于回填候选 evidence 时找原数据（避免 GPT-5.5 漏字段）
    evidence_lookup: dict[str, Evidence] = {}
    launch_lookup: dict[str, tuple[str | None, str | None]] = {}
    for ao in agent_outputs:
        for c in ao.top5_candidates:
            launch_lookup[_candidate_key(c.company, c.product)] = (
                c.product_launch_date,
                c.product_launch_date_evidence_url,
            )
            for fm in c.feature_match_table:
                for ev in fm.evidence:
                    if ev.url and ev.url not in evidence_lookup:
                        evidence_lookup[ev.url] = ev

    def _build_evidence(raw_list):
        out: list[Evidence] = []
        for re_ev in raw_list or []:
            if not isinstance(re_ev, dict):
                continue
            url = str(re_ev.get("url", "")).strip()
            if not url or url not in evidence_lookup:
                if url:
                    logger.info("丢弃未出现在复核输入中的证据 URL: %s", url[:80])
                continue
            ref = evidence_lookup.get(url)
            out.append(Evidence(
                url=url,
                title=str(re_ev.get("title") or (ref.title if ref else "")).strip(),
                source_type=_normalize_source_type(
                    re_ev.get("source_type") or (ref.source_type if ref else None)
                ),
                source_reliability=_normalize_reliability(
                    re_ev.get("source_reliability") or (ref.source_reliability if ref else None)
                ),
                summary=str(re_ev.get("summary") or (ref.summary if ref else "")).strip(),
                supported_features=[str(s) for s in (re_ev.get("supported_features") or [])],
            ))
        return out

    def _build_feature_matches(raw_list):
        from ..scoring import JUDGEMENT_SCORE
        out: list[FeatureMatch] = []
        for raw in raw_list or []:
            if not isinstance(raw, dict):
                continue
            fid = str(raw.get("feature_id", "")).strip()
            judg = str(raw.get("judgement", "证据不足")).strip()
            if judg not in JUDGEMENT_SCORE:
                judg = "证据不足"
            out.append(FeatureMatch(
                feature_id=fid,
                claim_feature=feature_text_by_id.get(fid, ""),
                judgement=judg,  # type: ignore[arg-type]
                score=JUDGEMENT_SCORE[judg],
                reasoning=str(raw.get("reasoning", "")).strip(),
                evidence=_build_evidence(raw.get("evidence")),
            ))
        return out

    auto_excluded: list[ReviewExcluded] = []
    top5: list[FinalCandidate] = []
    for raw in payload.get("top5", []) or []:
        if not isinstance(raw, dict):
            continue
        fmt = scoring.normalize_feature_matches(
            _build_feature_matches(raw.get("final_feature_table")),
            task.claim_features,
        )
        score = scoring.candidate_total_score(
            fmt,
            feature_ids=[f.feature_id for f in task.claim_features],
        )
        risk = _risk_from_score(score, fmt)
        raw_main_urls = {
            str(u) for u in (raw.get("main_evidence_urls") or [])
            if str(u) in evidence_lookup
        }
        evidence_urls = sorted({
            ev.url for fm in fmt for ev in fm.evidence if ev.url
        } | raw_main_urls)
        company = str(raw.get("company", "")).strip()
        product = str(raw.get("product", "")).strip()
        fallback_launch_date, fallback_launch_url = _lookup_launch_date(
            launch_lookup,
            company,
            product,
        )
        product_launch_date = (
            normalize_date_string(raw.get("product_launch_date"))
            or fallback_launch_date
        )
        product_launch_date_evidence_url = (
            str(raw.get("product_launch_date_evidence_url") or "").strip()
            or fallback_launch_url
        )
        hard = scoring.evaluate_hard_rules(
            company=company,
            product=product,
            assignees=task.patent.assignees,
            evidence_urls=evidence_urls,
            feature_matches=fmt,
            patent_application_date=task.patent.application_date,
            product_launch_date=product_launch_date,
        )
        ok, reason = scoring.passes_hard_rules(hard)
        if not ok:
            auto_excluded.append(ReviewExcluded(
                candidate_id=str(raw.get("candidate_id", "")).strip(),
                company=company,
                product=product,
                discard_reason=reason or "最终复核代码校验未通过",
                evidence_urls=evidence_urls,
            ))
            continue
        top5.append(FinalCandidate(
            rank=len(top5) + 1,
            candidate_id=str(raw.get("candidate_id", "")).strip() or f"M{len(top5)+1:03d}",
            company=company,
            product=product,
            aliases=[str(a) for a in (raw.get("aliases") or [])],
            product_launch_date=product_launch_date,
            product_launch_date_evidence_url=product_launch_date_evidence_url,
            score=round(score, 1),
            risk_level=risk,  # type: ignore[arg-type]
            final_feature_table=fmt,
            main_evidence_urls=evidence_urls,
            reason_for_top5=str(raw.get("reason_for_top5", "")).strip(),
            remaining_gaps=raw.get("remaining_gaps") or [],
        ))
        if len(top5) >= 5:
            break

    excluded = auto_excluded + [
        ReviewExcluded(
            candidate_id=str(x.get("candidate_id", "")),
            company=str(x.get("company", "")),
            product=str(x.get("product", "")),
            discard_reason=str(x.get("discard_reason", "")),
            evidence_urls=[str(u) for u in (x.get("evidence_urls") or [])],
        )
        for x in (payload.get("excluded") or []) if isinstance(x, dict)
    ]
    needs = [
        NeedsManualReview(
            candidate_id=str(x.get("candidate_id", "")),
            company=str(x.get("company", "")),
            product=str(x.get("product", "")),
            gap=str(x.get("gap", "")),
            suggested_search_direction=str(x.get("suggested_search_direction", "")),
        )
        for x in (payload.get("needs_manual_review") or []) if isinstance(x, dict)
    ]

    notes = str(payload.get("notes", "")).strip()
    if supplement_count:
        supplement_note = f"最终复核前已执行代码侧补搜，新增 {supplement_count} 条证据线索。"
        notes = f"{notes} {supplement_note}".strip()

    return FinalReport(
        patent_publication_no=task.patent.publication_no,
        claim_1_text=task.claim_1_text,
        claim_features=task.claim_features,
        top5=top5,
        excluded=excluded,
        needs_manual_review=needs,
        reviewer_model=f"codex:{model}",
        elapsed_seconds=round(time.monotonic() - t0, 2),
        notes=notes,
    )


# 兼容旧导入名（有些下游代码仍可能用 review_candidate_pool）
def review_candidate_pool(_pool, task, *, reasoning_effort: str = "medium"):
    """兼容入口 — 内部已不依赖 candidate_pool；新代码请用 ``review_agent_outputs``。"""
    raise RuntimeError(
        "review_candidate_pool 已废弃。请改用 review_agent_outputs(list[AgentOutput], task)。"
    )


def _load_supplement_cache(
    path: Path | None,
    task: TaskPackage,
) -> tuple[list[AgentOutput], int] | None:
    if path is None or not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("patent_publication_no") != task.patent.publication_no:
            logger.info(
                "[reviewer] supplement CACHE SKIP reason=pub_no_mismatch path=%s",
                path,
            )
            return None
        outputs = [
            AgentOutput.model_validate(item)
            for item in (raw.get("agent_outputs") or [])
        ]
        if not outputs:
            logger.info(
                "[reviewer] supplement CACHE SKIP reason=empty_outputs path=%s",
                path,
            )
            return None
        supplement_count = int(raw.get("supplement_count") or 0)
        logger.info(
            "[reviewer] supplement CACHE HIT path=%s agent_outputs=%d supplement_urls=%d",
            path, len(outputs), supplement_count,
        )
        return outputs, supplement_count
    except Exception as exc:  # noqa: BLE001
        logger.info("[reviewer] supplement CACHE SKIP path=%s error=%s", path, exc)
        return None


def _write_supplement_cache(
    path: Path,
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
    supplement_count: int,
) -> None:
    payload = {
        "version": 1,
        "patent_publication_no": task.patent.publication_no,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "supplement_count": supplement_count,
        "agent_outputs": [ao.model_dump() for ao in agent_outputs],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        logger.info(
            "[reviewer] supplement CACHE WRITE path=%s supplement_urls=%d",
            path, supplement_count,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("[reviewer] supplement CACHE WRITE failed path=%s error=%s", path, exc)


def _chat_json_with_retries(
    *,
    system: str,
    user_text: str,
    model: str,
    reasoning_effort: str,
    verbosity: str,
) -> dict[str, Any]:
    attempts = _env_int("REVIEWER_LLM_RETRY_ATTEMPTS", 3, minimum=1)
    delay = _env_float("REVIEWER_LLM_RETRY_DELAY_SECONDS", 60.0, minimum=0.0)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        logger.info(
            "[reviewer] GPT-5.5 review ATTEMPT %d/%d model=%s",
            attempt, attempts, model,
        )
        try:
            return codex.chat_json(
                system=system,
                user_text=user_text,
                model=model,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= attempts or not _is_retryable_llm_error(exc):
                logger.info(
                    "[reviewer] GPT-5.5 review FAIL attempt=%d/%d error=%s",
                    attempt, attempts, exc,
                )
                raise
            sleep_s = delay * attempt
            logger.warning(
                "[reviewer] GPT-5.5 review RETRY attempt=%d/%d sleep=%.0fs error=%s",
                attempt, attempts, sleep_s, exc,
            )
            if sleep_s > 0:
                time.sleep(sleep_s)
    raise RuntimeError(str(last_exc) if last_exc else "GPT-5.5 review failed")


def _is_retryable_llm_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        key in msg
        for key in (
            "429",
            "限流",
            "配额",
            "rate limit",
            "timeout",
            "timed out",
            "server disconnected",
            "connection",
            "temporarily",
            "try again",
        )
    )


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _risk_from_score(score: float, fmt: list[FeatureMatch]) -> str:
    has_clearly_unmatched = any(m.judgement == "明确不满足" for m in fmt)
    if score >= 85 and not has_clearly_unmatched:
        return "高度疑似落入"
    if score >= 70:
        return "中度疑似"
    if score >= 50:
        return "局部相似"
    return "弱相关"


def _supplement_agent_outputs(
    agent_outputs: list[AgentOutput],
    task: TaskPackage,
) -> tuple[list[AgentOutput], int]:
    """最终复核前对证据不足项执行代码侧补搜。"""
    outputs = [ao.model_copy(deep=True) for ao in agent_outputs]
    seen_queries = {
        evidence_strategy.normalize_query(q.query)
        for ao in outputs
        for q in ao.queries_used
        if q.query
    }
    added = 0
    seen_candidates = 0
    for ao in outputs:
        for cand in ao.top5_candidates:
            if seen_candidates >= REVIEW_SUPPLEMENT_MAX_CANDIDATES:
                return outputs, added
            seen_candidates += 1
            cand.feature_match_table = scoring.normalize_feature_matches(
                cand.feature_match_table,
                task.claim_features,
            )
            cand.score = scoring.candidate_total_score(
                cand.feature_match_table,
                feature_ids=[f.feature_id for f in task.claim_features],
            )
            added += _supplement_candidate(cand, task, seen_queries)
    return outputs, added


def _supplement_candidate(
    cand: Candidate,
    task: TaskPackage,
    seen_queries: set[str],
) -> int:
    existing_urls = {
        evidence_strategy.canonicalize_url(ev.url)
        for fm in cand.feature_match_table
        for ev in fm.evidence
        if ev.url
    } | {evidence_strategy.canonicalize_url(url) for url in cand.main_evidence_urls}
    gap_ids = {
        str(g.get("feature_id", "")).strip()
        for g in cand.remaining_gaps
        if isinstance(g, dict)
    }
    target_features = [
        fm for fm in cand.feature_match_table
        if (
            fm.judgement == "证据不足"
            or not any(ev.url for ev in fm.evidence)
            or fm.feature_id in gap_ids
        )
    ][:REVIEW_SUPPLEMENT_FEATURES_PER_CANDIDATE]

    added = 0
    feature_by_id = {f.feature_id: f for f in task.claim_features}
    target_match_by_id = {fm.feature_id: fm for fm in target_features}
    claim_targets = [
        feature_by_id[fm.feature_id]
        for fm in target_features
        if fm.feature_id in feature_by_id
    ]
    evidence_targets = evidence_strategy.build_evidence_targets(
        cand.company,
        cand.product,
        claim_targets,
        industry_tag=task.industry_tag,
        include_counter=True,
    )
    for target in evidence_targets[:REVIEW_SUPPLEMENT_TARGETS_PER_CANDIDATE]:
        target_feature_ids = tuple(
            fid for fid in target.feature_ids
            if fid in target_match_by_id
        )
        if not target_feature_ids:
            continue
        logger.info(
            "[reviewer] supplement START candidate=%s/%s target=%s features=%s",
            cand.company,
            cand.product,
            target.label,
            ",".join(target_feature_ids),
        )
        for query in target.queries[:REVIEW_SUPPLEMENT_QUERIES_PER_TARGET]:
            qkey = evidence_strategy.normalize_query(query)
            if qkey in seen_queries:
                logger.info(
                    "[reviewer] supplement SKIP duplicate_query target=%s query=%r",
                    target.target_id,
                    query,
                )
                continue
            seen_queries.add(qkey)
            logger.info(
                "[reviewer] supplement query target=%s features=%s query=%r",
                target.target_id,
                ",".join(target_feature_ids),
                query,
            )
            try:
                hits = pool.search(
                    query,
                    engines=REVIEW_SUPPLEMENT_ENGINES,
                    num_per_engine=REVIEW_SUPPLEMENT_HITS_PER_FEATURE,
                    log_context="[reviewer]",
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("review supplement search failed %r: %s", query, exc)
                continue
            hits = sorted(
                hits,
                key=lambda h: evidence_strategy.tier_rank(h.url, h.title),
                reverse=True,
            )
            for hit in hits:
                hit_url = evidence_strategy.canonicalize_url(hit.url)
                if not hit_url or hit_url in existing_urls:
                    if hit.url:
                        logger.info("[reviewer] supplement SKIP duplicate_url url=%s", hit_url)
                    continue
                if not evidence_strategy.is_relevant_hit(
                    hit_url,
                    hit.title,
                    hit.snippet,
                    cand.company,
                    cand.product,
                    cand.aliases,
                ):
                    logger.info(
                        "[reviewer] supplement SKIP low_relevance title=%r url=%s",
                        (hit.title or "")[:120],
                        hit_url,
                    )
                    continue
                hit.url = hit_url
                evidence = _evidence_from_hit(hit, target_feature_ids)
                for fid in target_feature_ids:
                    target_match_by_id[fid].evidence.append(evidence)
                cand.main_evidence_urls.append(hit_url)
                existing_urls.add(hit_url)
                added += 1
                logger.info(
                    "[reviewer] supplement ADD features=%s tier=%s source=%s url=%s",
                    ",".join(target_feature_ids),
                    evidence_strategy.tier_label(hit.url, hit.title),
                    evidence.source_type,
                    hit.url,
                )
    if added:
        cand.main_evidence_urls = sorted(set(cand.main_evidence_urls))
    return added


def _evidence_from_hit(hit, feature_ids: tuple[str, ...]) -> Evidence:
    text = hit.snippet or ""
    title = hit.title or ""
    try:
        page = pool.read_url(hit.url, log_context="[reviewer]")
        text = page.text or text
        title = page.title or title
    except Exception as exc:  # noqa: BLE001
        logger.info("review supplement read failed %s: %s", hit.url[:80], exc)
    return Evidence(
        url=hit.url,
        title=title,
        source_type=evidence_strategy.source_type_from_url_title(hit.url, title),
        source_reliability=evidence_strategy.reliability_from_url_title(hit.url, title),
        summary=(
            f"[最终复核补搜 / {evidence_strategy.tier_label(hit.url, title)}] "
            + text[:REVIEW_SUPPLEMENT_SUMMARY_CHARS]
        ).strip(),
        supported_features=list(feature_ids),
    )
