from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from jsonschema import Draft7Validator


Validator = Callable[[dict[str, Any], dict[str, Any]], None]
ASSET_DIR = Path(__file__).resolve().parent / "assets"
STATUS_SCORE = {"明确满足": 1.0, "可能满足": 0.8, "证据不足": 0.3, "明确不满足": 0.0}
GAP_STATUSES = {"可能满足", "证据不足"}
PROVIDER_SEARCH_CONTRACT = {
    "queries_min_items": 1,
    "queries_max_items": 200,
    "query_id": "可省略；服务器会按 Q001、Q002…重新编号",
    "query_max_characters": 500,
    "intent_values": [
        "claim_feature",
        "market_name",
        "specification",
        "industry_company",
        "launch_date",
        "evidence",
    ],
    "intent_fallback": "未知 intent 自动规范为 evidence，不阻断搜索",
    "language_values": ["zh", "en", "mixed"],
    "preferred_provider_values": ["tavily", "bocha", "exa", "brave"],
    "duplicate_queries": "服务器按去除首尾空白后的 query 文本去重",
}


@dataclass(frozen=True)
class Stage:
    name: str
    title: str
    prompt_file: str
    schema_file: str | None
    validator: Validator

    @property
    def prompt(self) -> str:
        return (ASSET_DIR / "agents" / self.prompt_file).read_text(encoding="utf-8")

    @property
    def schema(self) -> dict[str, Any] | None:
        if self.schema_file is None:
            return None
        return json.loads((ASSET_DIR / "schemas" / self.schema_file).read_text(encoding="utf-8"))


def _fail(errors: list[str]) -> None:
    if errors:
        raise ValueError("阶段产物校验失败：\n- " + "\n- ".join(errors[:60]))


def _schema_errors(stage: Stage, artifact: dict[str, Any]) -> list[str]:
    schema = stage.schema
    if schema is None:
        return []
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(artifact), key=lambda error: [str(part) for part in error.path])
    return [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    ]


def _claim_features(task_package: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    return {
        int(claim["claim_no"]): list(claim.get("features") or [])
        for claim in task_package.get("claims") or []
    }


def _valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _comparison_errors(comparison: dict[str, Any], *, claim_no: int) -> list[str]:
    errors: list[str] = []
    feature_id = str(comparison.get("feature_id") or "")
    status = comparison.get("status")
    expected = STATUS_SCORE.get(str(status))
    if expected is None or not math.isclose(_score(comparison.get("score")), expected, abs_tol=1e-9):
        errors.append(f"{feature_id}: status={status} 时 score 必须为 {expected}")
    evidence = comparison.get("evidence") or []
    for index, source in enumerate(evidence, start=1):
        if not _valid_http_url(source.get("url")):
            errors.append(f"{feature_id}.evidence[{index}] 必须是绝对 HTTP(S) URL")
    if status == "明确满足" and not evidence:
        errors.append(f"{feature_id}: 明确满足必须至少有一个公开 URL")
    if status in {"明确满足", "可能满足"}:
        reasoning = str(comparison.get("reasoning") or "")
        for marker in ("①", "②", "③", "(a)", "(b)", "(c)", "(d)"):
            if marker not in reasoning:
                errors.append(f"{feature_id}: reasoning 缺少严格推理标记 {marker}")
    gap = str(comparison.get("evidence_gap_brief") or "")
    if claim_no == 1 and status in GAP_STATUSES:
        lines = [line.strip() for line in gap.splitlines() if line.strip()]
        if len(lines) != 2 or not lines[0].startswith("还缺：") or not lines[1].startswith("下一步建议："):
            errors.append(f"{feature_id}: 权1缺口必须严格填写‘还缺/下一步建议’两行")
    elif gap:
        errors.append(f"{feature_id}: 非权1缺口或非缺口状态的 evidence_gap_brief 必须为空")
    if comparison.get("suggested_followup_queries"):
        errors.append(f"{feature_id}: 终判后 suggested_followup_queries 必须为空")
    return errors


def validate_task_package(artifact: dict[str, Any], case: dict[str, Any]) -> None:
    errors = _schema_errors(STAGES[0], artifact)
    patent = artifact.get("patent") or {}
    if patent.get("publication_no") != case["publication_no"]:
        errors.append("patent.publication_no 与案件公开号不一致")
    claims = artifact.get("claims") or []
    claim_numbers = [claim.get("claim_no") for claim in claims]
    if claim_numbers != sorted(set(claim_numbers)) or not claim_numbers or claim_numbers[0] != 1:
        errors.append("claims 必须从权利要求1开始并按编号严格递增且不重复")
    seen_feature_ids: set[str] = set()
    for claim in claims:
        claim_no = int(claim.get("claim_no") or 0)
        expected_ids = [f"C{claim_no}-F{index}" for index, _ in enumerate(claim.get("features") or [], start=1)]
        actual_ids = [feature.get("feature_id") for feature in claim.get("features") or []]
        if actual_ids != expected_ids:
            errors.append(f"权利要求{claim_no} feature_id 必须从 C{claim_no}-F1 连续编号")
        if seen_feature_ids.intersection(actual_ids):
            errors.append(f"权利要求{claim_no} 出现重复 feature_id")
        seen_feature_ids.update(actual_ids)
    if claims:
        if artifact.get("claim_1_text") != claims[0].get("claim_text"):
            errors.append("claim_1_text 必须等于 claims[0].claim_text")
        if artifact.get("claim_1_features") != claims[0].get("features"):
            errors.append("claim_1_features 必须等于 claims[0].features")
    _fail(errors)


def validate_top_competitors(artifact: dict[str, Any], case: dict[str, Any]) -> None:
    errors = _schema_errors(STAGES[1], artifact)
    task = case["artifacts"].get(STAGES[0].name) or {}
    if artifact.get("publication_no") != case["publication_no"]:
        errors.append("publication_no 与案件不一致")
    expected_ids = [feature["feature_id"] for feature in task.get("claim_1_features") or []]
    top = artifact.get("top_competitors") or []
    if len(top) > 5:
        errors.append("top_competitors 最多5个")
    seen_top_companies: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for bucket_name in ("top_competitors", "excluded_candidates"):
        for item in artifact.get(bucket_name) or []:
            candidate = item.get("candidate") or {}
            label = str(candidate.get("candidate_id") or "候选")
            company = str(candidate.get("company") or "").strip().lower()
            product_name = str(candidate.get("product_name") or "")
            if not ("（" in product_name and "）" in product_name) and not ("(" in product_name and ")" in product_name):
                errors.append(f"{label}: product_name 必须用括号锁定唯一 SKU")
            pair = (company, product_name.strip().lower())
            if pair in seen_pairs:
                errors.append(f"{label}: (company, product_name) 重复")
            seen_pairs.add(pair)
            if bucket_name == "top_competitors":
                if company in seen_top_companies:
                    errors.append(f"{label}: top_competitors 中同公司只能保留最高分产品")
                seen_top_companies.add(company)
            comparisons = item.get("comparisons") or []
            actual_ids = [comparison.get("feature_id") for comparison in comparisons]
            if actual_ids != expected_ids:
                errors.append(f"{label}: comparisons 必须按顺序完整覆盖权1全部 feature")
            scores = []
            for comparison in comparisons:
                # 模块二不填写 gap brief，但其余严格规则与模块三一致。
                copied = dict(comparison)
                copied["evidence_gap_brief"] = ""
                errors.extend(_comparison_errors(copied, claim_no=0))
                scores.append(_score(comparison.get("score")))
            expected_total = 0.0 if item.get("disqualified") else (sum(scores) / len(scores) * 100 if scores else 0.0)
            if not math.isclose(_score(item.get("total_score")), expected_total, abs_tol=0.02):
                errors.append(f"{label}: total_score 应为 {expected_total:.2f}")
            has_negative = any(comparison.get("status") == "明确不满足" for comparison in comparisons)
            if has_negative and not item.get("disqualified"):
                errors.append(f"{label}: 权1明确不满足必须 disqualified=true")
            if bucket_name == "top_competitors" and item.get("disqualified"):
                errors.append(f"{label}: 失效候选不能进入 top_competitors")
            if bucket_name == "excluded_candidates" and not item.get("disqualified"):
                errors.append(f"{label}: excluded_candidates 中候选必须 disqualified=true")
    top_scores = [_score(item.get("total_score")) for item in top]
    if top_scores != sorted(top_scores, reverse=True):
        errors.append("top_competitors 必须按 total_score 降序排列")
    _fail(errors)


def validate_full_claim_chart(artifact: dict[str, Any], case: dict[str, Any]) -> None:
    errors = _schema_errors(STAGES[2], artifact)
    task = case["artifacts"].get(STAGES[0].name) or {}
    expected = _claim_features(task)
    if artifact.get("publication_no") != case["publication_no"]:
        errors.append("publication_no 与案件不一致")
    seen_top_companies: set[str] = set()
    for bucket_name in ("top_competitors", "excluded_candidates"):
        for item in artifact.get(bucket_name) or []:
            candidate = item.get("candidate") or {}
            label = str(candidate.get("candidate_id") or "候选")
            if bucket_name == "top_competitors":
                company = str(candidate.get("company") or "").strip().lower()
                if company in seen_top_companies:
                    errors.append(f"{label}: top_competitors 中同公司只能保留最高分产品")
                seen_top_companies.add(company)
            charts = item.get("claim_charts") or []
            if [chart.get("claim_no") for chart in charts] != list(expected):
                errors.append(f"{label}: claim_charts 必须按顺序覆盖全部权利要求")
            claim1_score = 0.0
            claim1_negative = False
            for chart in charts:
                claim_no = int(chart.get("claim_no") or 0)
                expected_ids = [feature["feature_id"] for feature in expected.get(claim_no, [])]
                comparisons = chart.get("comparisons") or []
                if [comparison.get("feature_id") for comparison in comparisons] != expected_ids:
                    errors.append(f"{label}/权利要求{claim_no}: 必须按顺序覆盖全部 feature")
                scores = []
                negative = False
                for comparison in comparisons:
                    errors.extend(_comparison_errors(comparison, claim_no=claim_no))
                    scores.append(_score(comparison.get("score")))
                    negative = negative or comparison.get("status") == "明确不满足"
                expected_claim_score = 0.0 if negative else (sum(scores) / len(scores) * 100 if scores else 0.0)
                if not math.isclose(_score(chart.get("claim_score")), expected_claim_score, abs_tol=0.02):
                    errors.append(f"{label}/权利要求{claim_no}: claim_score 应为 {expected_claim_score:.2f}")
                if claim_no == 1:
                    claim1_score = expected_claim_score
                    claim1_negative = negative
            expected_total = 0.0 if item.get("disqualified") else claim1_score
            if not math.isclose(_score(item.get("claim_1_score")), claim1_score, abs_tol=0.02):
                errors.append(f"{label}: claim_1_score 与权1不一致")
            if not math.isclose(_score(item.get("total_score")), expected_total, abs_tol=0.02):
                errors.append(f"{label}: total_score 必须只取权1得分")
            if claim1_negative and not item.get("disqualified"):
                errors.append(f"{label}: 权1明确不满足必须失效")
            if bucket_name == "top_competitors" and item.get("disqualified"):
                errors.append(f"{label}: 失效候选不能进入 top_competitors")
            if bucket_name == "excluded_candidates" and not item.get("disqualified"):
                errors.append(f"{label}: excluded_candidates 中候选必须失效")
    _fail(errors)


def validate_report(artifact: dict[str, Any], case: dict[str, Any]) -> None:
    markdown = artifact.get("report_markdown")
    errors: list[str] = []
    if not isinstance(markdown, str) or len(markdown.strip()) < 500:
        errors.append("report_markdown 至少需要500字符")
        _fail(errors)
        return
    for heading in ("## 1. 专利详细信息", "## 2. 整体侵权风险评估", "## 3. TOP"):
        if heading not in markdown:
            errors.append(f"报告缺少章节：{heading}")
    if re.search(r"^# ", markdown, flags=re.MULTILINE):
        errors.append("报告禁止一级标题")
    full = case["artifacts"].get(STAGES[2].name) or {}
    top = full.get("top_competitors") or []
    expected_top_heading = f"## 3. TOP{len(top)} 竞品深度对比"
    if expected_top_heading not in markdown:
        errors.append(f"TOP-N 标题必须为：{expected_top_heading}")
    for rank, item in enumerate(top, start=1):
        candidate = item.get("candidate") or {}
        label = f"{candidate.get('company', '')} {candidate.get('product_name', '')}".strip()
        if f"#### TOP{rank}: {label}" not in markdown:
            errors.append(f"报告缺少候选章节：TOP{rank} {label}")
        if "| **SKU 锁定** |" not in markdown:
            errors.append("每个候选必须包含 SKU 锁定行")
        for chart in item.get("claim_charts") or []:
            if f"##### 权利要求 {chart.get('claim_no')}" not in markdown:
                errors.append(f"{label}: 缺少权利要求{chart.get('claim_no')}小节")
            for comparison in chart.get("comparisons") or []:
                if str(comparison.get("feature_id")) not in markdown:
                    errors.append(f"{label}: 报告缺少 {comparison.get('feature_id')}")
                for source in comparison.get("evidence") or []:
                    if source.get("url") and source["url"] not in markdown:
                        errors.append(f"{label}/{comparison.get('feature_id')}: 报告缺少证据 URL {source['url']}")
    max_score = max((_score(item.get("total_score")) for item in top), default=0.0)
    if max_score >= 80 and "相似专利人工核查" not in markdown:
        errors.append("最高分≥80时必须输出相似专利人工核查章节")
    _fail(errors)


STAGES: tuple[Stage, ...] = (
    Stage("module_1_decompose", "模块一：拆解权利要求", "decompose.md", "task_package.schema.json", validate_task_package),
    Stage("module_2_competitor_search", "模块二：竞品搜索与权1判定", "competitor_search.md", "top_competitor_report.schema.json", validate_top_competitors),
    Stage("module_3_full_claim_chart", "模块三：全部权利要求 Claim Chart", "full_claim_chart.md", "full_claim_chart_report.schema.json", validate_full_claim_chart),
    Stage("module_4_report", "模块四：生成 Markdown 与 PDF 报告", "report.md", None, validate_report),
)


def normalize_submission_artifact(stage_name: str, artifact: dict[str, Any]) -> dict[str, Any]:
    """Normalize harmless formatting before strict business validation."""
    normalized = dict(artifact)
    if stage_name != STAGES[3].name:
        return normalized
    markdown = normalized.get("report_markdown")
    if not isinstance(markdown, str):
        return normalized
    lines = markdown.splitlines()
    first_content = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_content is None or not lines[first_content].startswith("# "):
        return normalized
    remaining = lines[first_content + 1 :]
    while remaining and not remaining[0].strip():
        remaining.pop(0)
    normalized["report_markdown"] = "\n".join(remaining) + ("\n" if markdown.endswith("\n") else "")
    return normalized


def _provider_bucket(case: dict[str, Any], stage_name: str) -> dict[str, Any]:
    return ((case.get("artifacts") or {}).get("_provider_search") or {}).get(stage_name) or {}


def effective_search_strategy(case: dict[str, Any], *, provider_keys_available: bool) -> str:
    if not provider_keys_available:
        return "codex_only"
    index = int(case["stage_index"])
    if index >= len(STAGES):
        buckets = (case.get("artifacts") or {}).get("_provider_search") or {}
        return "hybrid" if any(bucket.get("result_count", 0) for bucket in buckets.values()) else "codex_fallback"
    provider_search = _provider_bucket(case, STAGES[index].name)
    if provider_search:
        return "hybrid" if provider_search.get("result_count", 0) else "codex_fallback"
    return "hybrid_pending" if index in {1, 2} else "codex_only"


def _stage_inputs(case: dict[str, Any], stage: Stage) -> dict[str, Any]:
    artifacts = case["artifacts"]
    if stage.name == STAGES[0].name:
        return {"publication_no": case["publication_no"]}
    if stage.name == STAGES[1].name:
        return {"task_package": artifacts[STAGES[0].name]}
    if stage.name == STAGES[2].name:
        return {
            "task_package": artifacts[STAGES[0].name],
            "top_competitors": artifacts[STAGES[1].name],
        }
    return {
        "task_package": artifacts[STAGES[0].name],
        "full_claim_chart": artifacts[STAGES[2].name],
    }


def _mcp_adaptation(stage: Stage, case: dict[str, Any], *, provider_keys_available: bool) -> str:
    lines = [
        "\n\n# MCP 执行适配（优先于上文中的本地文件路径/Task tool 描述）",
        "主 Codex 必须为当前模块派生一个新的独立 subagent，把上文完整规则与本次 `inputs` 原样交给它；主 Codex 不自行完成模块内容。",
        "当前模块 subagent 必须完整执行全部业务规则，不得压缩、合并或跳步；四个模块不得合并到一次推理。",
        "输入材料位于本次 MCP 返回的 `inputs`；不要读写 skill 路径或本地 output_dir。",
        f"完成后调用 `analysis_submit`，stage 必须为 `{stage.name}`，artifact 只放上文规定的最终结构化产物。",
        "若服务器返回 Schema/业务校验错误，按错误逐项修正后重新提交，不要降级输出。",
    ]
    if stage.name in {STAGES[1].name, STAGES[2].name}:
        lines.extend(
            [
                "Codex 内置网页搜索、页面打开和视觉工具始终必须参与；在 analysis_submit 的 codex_builtin_queries 参数中提交实际运行过的查询。",
                "外部搜索摘要只能作为发现线索，证据 URL 仍须用 Codex 打开正文、验活、看图并核对 SKU 后才能写入报告。",
            ]
        )
        if provider_keys_available:
            lines.extend(
                [
                    "检测到用户配置的外部搜索 Key：候选发现时调用 `provider_search(search_mode='discovery')`，传入含 query/query_id/intent/language/preferred_providers 的 QueryPlan；单次可传 1-200 条，query_id 可省略且由服务器重新编号，每条 query 最多使用 3 个已配置源。",
                    "对候选证据和缺口补搜调用 `provider_search(search_mode='evidence')`；该模式会并发尝试全部已配置源。单源无额度/失败时继续其他源和 Codex。",
                    "MCP 返回的外部结果只做字段统一和机械 URL 去重；你必须在本地把它与 Codex 内置结果合并，并负责申请人/关联品牌过滤、语义去重、正文验活、图片检查和 SKU 一致性判断。",
                ]
            )
        else:
            lines.append("用户未配置外部搜索 Key：直接按完整规则使用 Codex 内置搜索，不得降低候选数、搜索维度或证据标准。")
    if stage.name == STAGES[3].name:
        lines.append("不要在用户电脑运行 Python/WeasyPrint。提交 `{'report_markdown': '<完整 Markdown>'}`，MCP 服务器会跨平台渲染 PDF。report_markdown 的首个非空行必须是 `## 1. 专利详细信息`，不得添加 `# ` 一级标题或前言。")
    return "\n".join(lines)


def current_work_item(case: dict[str, Any], *, provider_keys_available: bool) -> dict[str, Any]:
    index = int(case["stage_index"])
    if index >= len(STAGES):
        return {"state": "completed", "message": "四模块分析已完成，可以获取 PDF 报告。"}
    stage = STAGES[index]
    provider_search = _provider_bucket(case, stage.name)
    response: dict[str, Any] = {
        "state": "work_required",
        "case_id": case["id"],
        "stage": stage.name,
        "title": stage.title,
        "search_strategy": effective_search_strategy(case, provider_keys_available=provider_keys_available),
        "instruction": stage.prompt + _mcp_adaptation(stage, case, provider_keys_available=provider_keys_available),
        "inputs": _stage_inputs(case, stage),
        "submit_with": "analysis_submit",
    }
    if stage.schema is not None:
        response["output_schema"] = stage.schema
    if stage.name in {STAGES[1].name, STAGES[2].name}:
        response["provider_search_contract"] = PROVIDER_SEARCH_CONTRACT
        response["technology_sites_config"] = (ASSET_DIR / "configs" / "technology_tags.toml").read_text(encoding="utf-8")
        response["provider_search"] = provider_search or {
            "configured": provider_keys_available,
            "result_count": 0,
            "results": [],
            "fallback_reason": "not_attempted" if provider_keys_available else "no_provider_keys",
        }
    return response


def validate_submission(
    case: dict[str, Any],
    stage_name: str,
    artifact: dict[str, Any],
    *,
    provider_keys_available: bool = False,
) -> tuple[int, bool]:
    index = int(case["stage_index"])
    if case["status"] == "completed" or index >= len(STAGES):
        raise ValueError("案件已经完成，不能继续提交")
    stage = STAGES[index]
    if stage.name != stage_name:
        raise ValueError(f"当前应提交 {stage.name}，收到的是 {stage_name}")
    if provider_keys_available and stage.name == STAGES[1].name:
        search_modes = set(_provider_bucket(case, stage.name).get("search_modes") or [])
        missing_modes = {"discovery", "evidence"} - search_modes
        if missing_modes:
            raise ValueError(
                "检测到用户已配置搜索 Key，模块二必须分别调用 discovery 候选发现和 evidence 证据补搜；"
                f"缺少：{', '.join(sorted(missing_modes))}"
            )
    if provider_keys_available and stage.name == STAGES[2].name:
        module_two = case["artifacts"].get(STAGES[1].name) or {}
        has_gaps = any(
            comparison.get("status") in GAP_STATUSES
            for candidate in module_two.get("top_competitors") or []
            for comparison in candidate.get("comparisons") or []
        )
        search_modes = set(_provider_bucket(case, stage.name).get("search_modes") or [])
        if has_gaps and "evidence" not in search_modes:
            raise ValueError("模块二仍有权1证据缺口且用户已配置搜索 Key，模块三必须调用 evidence 模式补搜；失败结果也算已尝试")
    stage.validator(artifact, case)
    next_index = index + 1
    return next_index, next_index >= len(STAGES)
