from copy import deepcopy

import pytest

from artifacts import full_claim_chart, report_artifact, task_package, top_competitors
from patentradar_mcp.workflow import (
    STAGES,
    current_work_item,
    normalize_submission_artifact,
    validate_submission,
)


def _case(*, stage_index: int = 0, artifacts: dict | None = None) -> dict:
    return {
        "id": "case_1",
        "publication_no": "CN114512759B",
        "search_mode": "auto",
        "status": "active",
        "stage_index": stage_index,
        "artifacts": artifacts or {},
    }


def test_first_stage_contains_full_skill_prompt_and_schema() -> None:
    work = current_work_item(_case(), provider_keys_available=False)
    assert work["stage"] == "module_1_decompose"
    assert "if-then-else 整体保留" in work["instruction"]
    assert work["output_schema"]["title"] == "TaskPackage"
    assert validate_submission(_case(), STAGES[0].name, task_package()) == (1, False)


def test_module_two_hybrid_instruction_and_provider_results() -> None:
    case = _case(
        stage_index=1,
        artifacts={
            STAGES[0].name: task_package(),
            "_provider_search": {
                STAGES[1].name: {"result_count": 1, "results": [{"url": "https://example.com/spec"}]}
            },
        },
    )
    work = current_work_item(case, provider_keys_available=True)
    assert work["search_strategy"] == "hybrid"
    assert "筛 15-25 个候选" in work["instruction"]
    assert "最终榜单按公司去重" in work["instruction"]
    assert work["provider_search"]["result_count"] == 1
    assert work["provider_search_contract"]["queries_max_items"] == 200
    followups = work["output_schema"]["definitions"]["FeatureComparison"]["properties"][
        "suggested_followup_queries"
    ]
    assert followups["maxItems"] == 0
    assert validate_submission(case, STAGES[1].name, top_competitors()) == (2, False)


def test_module_two_schema_rejects_unconsumed_followup_queries() -> None:
    case = _case(stage_index=1, artifacts={STAGES[0].name: task_package()})
    artifact = top_competitors()
    artifact["top_competitors"][0]["comparisons"][0]["suggested_followup_queries"] = ["继续搜索"]

    with pytest.raises(ValueError, match="suggested_followup_queries"):
        validate_submission(case, STAGES[1].name, artifact)


def test_module_two_with_keys_requires_discovery_and_evidence_search_modes() -> None:
    case = _case(
        stage_index=1,
        artifacts={
            STAGES[0].name: task_package(),
            "_provider_search": {
                STAGES[1].name: {"search_modes": ["discovery"], "result_count": 0, "results": []}
            },
        },
    )

    with pytest.raises(ValueError, match="evidence"):
        validate_submission(case, STAGES[1].name, top_competitors(), provider_keys_available=True)

    case["artifacts"]["_provider_search"][STAGES[1].name]["search_modes"].append("evidence")
    assert validate_submission(
        case,
        STAGES[1].name,
        top_competitors(),
        provider_keys_available=True,
    ) == (2, False)


def test_module_two_rejects_multiple_skus_from_same_company_in_top_five() -> None:
    case = _case(stage_index=1, artifacts={STAGES[0].name: task_package()})
    artifact = top_competitors()
    second = deepcopy(artifact["top_competitors"][0])
    second["candidate"]["candidate_id"] = "P02"
    second["candidate"]["product_name"] = "示例产品（SKU-2 / 2025款）"
    second["candidate"]["product_name_en"] = "Example Product (SKU-2 / MY2025)"
    artifact["top_competitors"].append(second)

    with pytest.raises(ValueError, match="同公司只能保留最高分产品"):
        validate_submission(case, STAGES[1].name, artifact)


def test_module_three_requires_complete_claim_chart_and_gap_brief() -> None:
    case = _case(
        stage_index=2,
        artifacts={STAGES[0].name: task_package(), STAGES[1].name: top_competitors()},
    )
    assert validate_submission(case, STAGES[2].name, full_claim_chart()) == (3, False)
    broken = full_claim_chart()
    broken["top_competitors"][0]["claim_charts"][0]["comparisons"][0]["evidence_gap_brief"] = "证据不足"
    with pytest.raises(ValueError, match="还缺/下一步建议"):
        validate_submission(case, STAGES[2].name, broken)


def test_module_three_rejects_duplicate_company_reintroduced_into_top_five() -> None:
    case = _case(
        stage_index=2,
        artifacts={STAGES[0].name: task_package(), STAGES[1].name: top_competitors()},
    )
    artifact = full_claim_chart()
    second = deepcopy(artifact["top_competitors"][0])
    second["candidate"]["candidate_id"] = "P02"
    second["candidate"]["product_name"] = "示例产品（SKU-2 / 2025款）"
    second["candidate"]["product_name_en"] = "Example Product (SKU-2 / MY2025)"
    artifact["top_competitors"].append(second)

    with pytest.raises(ValueError, match="同公司只能保留最高分产品"):
        validate_submission(case, STAGES[2].name, artifact)


def test_report_structure_validation_completes_four_modules() -> None:
    case = _case(
        stage_index=3,
        artifacts={
            STAGES[0].name: task_package(),
            STAGES[1].name: top_competitors(),
            STAGES[2].name: full_claim_chart(),
        },
    )
    assert validate_submission(case, STAGES[3].name, report_artifact()) == (4, True)


def test_report_leading_h1_is_removed_before_validation() -> None:
    case = _case(
        stage_index=3,
        artifacts={
            STAGES[0].name: task_package(),
            STAGES[1].name: top_competitors(),
            STAGES[2].name: full_claim_chart(),
        },
    )
    artifact = report_artifact()
    artifact["report_markdown"] = "# CN114512759B 专利侵权竞品分析\n\n" + artifact["report_markdown"]

    normalized = normalize_submission_artifact(STAGES[3].name, artifact)

    assert normalized["report_markdown"].startswith("## 1. 专利详细信息")
    assert validate_submission(case, STAGES[3].name, normalized) == (4, True)


def test_rejects_out_of_order_stage() -> None:
    with pytest.raises(ValueError, match="当前应提交 module_1_decompose"):
        validate_submission(_case(), STAGES[1].name, top_competitors())
