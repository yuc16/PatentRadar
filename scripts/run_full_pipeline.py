"""End-to-end: 模块二 → 三 → 四（不截候选数）。

模块一固定复用 tests/decompose/outputs/<PUB>/task_package.json。
backend 由当前 .env 决定（PATENTRADAR_LLM_BACKEND=codex|openai）。

用法：
    uv run python scripts/run_full_pipeline.py <PUB> --out-dir <DIR>
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

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

ROOT = Path(__file__).resolve().parents[1]
app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def main(
    publication_no: str = typer.Argument(..., help="例如 CN114512759B"),
    out_dir: Path = typer.Option(..., "--out-dir", help="所有产物写入此目录"),
    max_workers_step4: int = typer.Option(3, "--workers-step4"),
    max_workers_module3: int = typer.Option(2, "--workers-module3"),
) -> None:
    task_package_path = (
        ROOT / "tests" / "decompose" / "outputs" / publication_no / "task_package.json"
    )
    if not task_package_path.exists():
        print(f"FATAL: task_package not found at {task_package_path}", file=sys.stderr)
        raise typer.Exit(code=1)

    module_two_dir = out_dir / "module_two"
    module_three_dir = out_dir / "module_three"
    module_four_dir = out_dir / "module_four"
    for d in (module_two_dir, module_three_dir, module_four_dir):
        d.mkdir(parents=True, exist_ok=True)

    print(f"[1/7] task_package <- {task_package_path}")
    tp = load_task_package(task_package_path)
    print(
        f"      patent={tp.patent.publication_no} country={tp.patent.country_code} "
        f"claims={len(tp.claims)} tag={tp.technology_tag}"
    )

    print("[2/7] module-two step1: query plan")
    plan = run_step1_generate_queries(task_package=tp, output_dir=module_two_dir)
    print(f"      queries={len(plan.queries)} domains={len(plan.applicant_self_signals.domains)}"
          f" aliases={len(plan.applicant_self_signals.aliases)}")

    print("[3/7] module-two step2: search")
    results = run_step2_search_results(
        task_package=tp, query_plan=plan, output_dir=module_two_dir
    )
    print(f"      raw_results={len(results.results)}")

    print("[4/7] module-two step3: candidate extraction")
    shortlist = run_step3_filter_candidates(
        task_package=tp, search_results=results, output_dir=module_two_dir
    )
    print(f"      candidates={len(shortlist.candidates)}")
    if not shortlist.candidates:
        print("FATAL: 0 candidates", file=sys.stderr)
        raise typer.Exit(code=2)

    print(f"[5/7] module-two step4 (full, {len(shortlist.candidates)} candidates) + step5")
    evidence = run_step4_map_evidence(
        task_package=tp,
        shortlist=shortlist,
        output_dir=module_two_dir,
        query_plan=plan,
        max_workers=max_workers_step4,
    )
    top_report = run_step5_rank_top(
        task_package=tp, evidence_results=evidence, output_dir=module_two_dir
    )
    print(f"      top_competitors={len(top_report.top_competitors)} "
          f"excluded={len(top_report.excluded_candidates)}")
    for c in top_report.top_competitors:
        print(
            f"      {c.candidate.candidate_id}: {c.candidate.company} "
            f"{c.candidate.product_name} {c.candidate.product_version} "
            f"total_score={c.total_score}"
        )

    print("[6/7] module-three: full claim chart")
    full_chart = run_full_claim_chart(
        task_package=tp,
        top_report=top_report,
        output_dir=module_three_dir,
        self_signals=plan.applicant_self_signals,
        max_workers=max_workers_module3,
    )
    print(f"      completed={len(full_chart.top_competitors)} "
          f"excluded={len(full_chart.excluded_candidates)}")
    for c in full_chart.top_competitors:
        print(f"      {c.candidate.candidate_id}: total_score={c.total_score}")

    print("[7/7] module-four: report")
    report_path = run_report(
        task_package=tp,
        full_claim_chart_report=full_chart,
        output_dir=module_four_dir,
    )
    print(f"      wrote {report_path}")
    print("DONE")


if __name__ == "__main__":
    app()
