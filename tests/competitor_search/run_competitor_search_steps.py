"""Manual real-test runner for module two.

Example:
uv run python tests/competitor_search/run_competitor_search_steps.py \
  --task-package tests/decompose/outputs/CN114512759B/task_package.json \
  --step 1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patentradar.modules.competitor_search.pipeline import (
    load_candidate_evidence,
    load_candidate_shortlist,
    load_query_plan,
    load_search_results,
    load_task_package,
    run_step1_generate_queries,
    run_step2_search_results,
    run_step3_filter_candidates,
    run_step4_map_evidence,
    run_step5_rank_top,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-package", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/competitor_search/outputs/CN114512759B"),
    )
    parser.add_argument("--step", choices=["1", "2", "3", "4", "5", "all"], required=True)
    parser.add_argument("--max-workers", type=int, default=3)
    args = parser.parse_args()

    task_package = load_task_package(args.task_package)
    output_dir = args.output_dir

    if args.step in {"1", "all"}:
        query_plan = run_step1_generate_queries(task_package=task_package, output_dir=output_dir)
        print(json.dumps({"step": 1, "query_count": len(query_plan.queries)}, ensure_ascii=False))
        if args.step == "1":
            return
    else:
        query_plan = load_query_plan(output_dir / "step1_query_plan.json")

    if args.step in {"2", "all"}:
        search_results = run_step2_search_results(
            task_package=task_package,
            query_plan=query_plan,
            output_dir=output_dir,
        )
        print(json.dumps({"step": 2, "result_count": len(search_results.results)}, ensure_ascii=False))
        if args.step == "2":
            return
    else:
        search_results = load_search_results(output_dir / "step2_search_results.json")

    if args.step in {"3", "all"}:
        shortlist = run_step3_filter_candidates(
            task_package=task_package,
            search_results=search_results,
            output_dir=output_dir,
        )
        print(json.dumps({"step": 3, "candidate_count": len(shortlist.candidates)}, ensure_ascii=False))
        if args.step == "3":
            return
    else:
        shortlist = load_candidate_shortlist(output_dir / "step3_candidate_shortlist.json")

    if args.step in {"4", "all"}:
        evidence_results = run_step4_map_evidence(
            task_package=task_package,
            shortlist=shortlist,
            output_dir=output_dir,
            max_workers=args.max_workers,
        )
        print(json.dumps({"step": 4, "evaluated_count": len(evidence_results)}, ensure_ascii=False))
        if args.step == "4":
            return
    else:
        evidence_results = load_candidate_evidence(output_dir / "step4_candidate_evidence.json")

    report = run_step5_rank_top(
        task_package=task_package,
        evidence_results=evidence_results,
        output_dir=output_dir,
    )
    print(json.dumps({"step": 5, "top_count": len(report.top_competitors)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
