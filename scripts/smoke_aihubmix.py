"""One-shot smoke test: CN114512759B 全链路过 OpenAI 兼容 backend。

复用模块一 task_package（tests/decompose/outputs/...），重新跑模块二
step1→step5，但在 step4 之前把 shortlist 截成 1 个候选；之后模块三/四
也只处理这一个候选。

产物全部写到 tests/smoke_aihubmix/CN114512759B/，不覆盖既有 outputs。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from patentradar.modules.competitor_search.pipeline import (
    load_task_package,
    run_step1_generate_queries,
    run_step2_search_results,
    run_step3_filter_candidates,
    run_step4_map_evidence,
    run_step5_rank_top,
)
from patentradar.modules.full_claim_chart import run_full_claim_chart
from patentradar.modules.report import run_report


PUB = "CN114512759B"
ROOT = Path(__file__).resolve().parents[1]
TASK_PACKAGE = ROOT / "tests" / "decompose" / "outputs" / PUB / "task_package.json"
OUT_ROOT = ROOT / "tests" / "smoke_aihubmix" / PUB


def main() -> int:
    if not TASK_PACKAGE.exists():
        print(f"FATAL: task_package not found at {TASK_PACKAGE}", file=sys.stderr)
        return 1

    module_two_dir = OUT_ROOT / "module_two"
    module_three_dir = OUT_ROOT / "module_three"
    module_four_dir = OUT_ROOT / "module_four"
    for d in (module_two_dir, module_three_dir, module_four_dir):
        d.mkdir(parents=True, exist_ok=True)

    print(f"[1/7] loading task_package from {TASK_PACKAGE}")
    task_package = load_task_package(TASK_PACKAGE)
    print(
        f"      patent={task_package.patent.publication_no} "
        f"country={task_package.patent.country_code} "
        f"claims={len(task_package.claims)} "
        f"tag={task_package.technology_tag}"
    )

    print("[2/7] module-two step1: query plan")
    query_plan = run_step1_generate_queries(
        task_package=task_package,
        output_dir=module_two_dir,
    )
    print(f"      queries={len(query_plan.queries)} domains={len(query_plan.applicant_self_signals.domains)} aliases={len(query_plan.applicant_self_signals.aliases)}")

    print("[3/7] module-two step2: search providers")
    search_results = run_step2_search_results(
        task_package=task_package,
        query_plan=query_plan,
        output_dir=module_two_dir,
    )
    print(f"      raw_results={len(search_results.results)}")

    print("[4/7] module-two step3: candidate extraction (LLM)")
    shortlist = run_step3_filter_candidates(
        task_package=task_package,
        search_results=search_results,
        output_dir=module_two_dir,
    )
    print(f"      candidates={len(shortlist.candidates)}")
    if not shortlist.candidates:
        print("FATAL: step3 returned 0 candidates; cannot continue", file=sys.stderr)
        return 2

    # 链路验证：只保留第一个候选
    capped = shortlist.model_copy(update={"candidates": shortlist.candidates[:1]})
    (module_two_dir / "step3_candidate_shortlist.capped.json").write_text(
        json.dumps(capped.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"      capped_to candidate_id={capped.candidates[0].candidate_id} "
          f"company={capped.candidates[0].company}")

    print("[5/7] module-two step4 (capped, 1 candidate) + step5")
    evidence_results = run_step4_map_evidence(
        task_package=task_package,
        shortlist=capped,
        output_dir=module_two_dir,
        query_plan=query_plan,
        max_workers=1,
    )
    print(f"      evidence_results={len(evidence_results)}")
    top_report = run_step5_rank_top(
        task_package=task_package,
        evidence_results=evidence_results,
        output_dir=module_two_dir,
    )
    print(f"      top_competitors={len(top_report.top_competitors)} "
          f"excluded={len(top_report.excluded_candidates)}")
    if top_report.top_competitors:
        c0 = top_report.top_competitors[0]
        print(f"      TOP1: {c0.candidate.company} / total_score={c0.total_score}")

    print("[6/7] module-three: full claim chart (1 candidate)")
    full_chart = run_full_claim_chart(
        task_package=task_package,
        top_report=top_report,
        output_dir=module_three_dir,
        self_signals=query_plan.applicant_self_signals,
        max_workers=1,
    )
    print(f"      completed_candidates={len(full_chart.top_competitors)} "
          f"excluded={len(full_chart.excluded_candidates)}")

    print("[7/7] module-four: report")
    report_path = run_report(
        task_package=task_package,
        full_claim_chart_report=full_chart,
        output_dir=module_four_dir,
    )
    print(f"      wrote {report_path}")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
