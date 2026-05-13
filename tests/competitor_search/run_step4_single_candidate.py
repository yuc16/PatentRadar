"""Single-candidate step-4 runner for fast iteration / inspection.

Example:
  python tests/competitor_search/run_step4_single_candidate.py \
    --task-package tests/decompose/outputs/CN114512759B/task_package.json \
    --shortlist tests/competitor_search/outputs/CN114512759B/step3_candidate_shortlist.json \
    --candidate-id P02 \
    --output-dir tests/competitor_search/outputs/CN114512759B/step4_single
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from patentradar.modules.competitor_search.evidence_mapper import map_evidence_for_batch
from patentradar.modules.competitor_search.pipeline import (
    load_candidate_shortlist,
    load_task_package,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-package", required=True, type=Path)
    parser.add_argument("--shortlist", required=True, type=Path)
    parser.add_argument("--candidate-id", required=True, help="e.g. P02")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    task_package = load_task_package(args.task_package)
    shortlist = load_candidate_shortlist(args.shortlist)

    target = next(
        (c for c in shortlist.candidates if c.candidate_id == args.candidate_id),
        None,
    )
    if target is None:
        raise SystemExit(f"candidate {args.candidate_id} not found in shortlist")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    visual_log_dir = args.output_dir / "visual_log"
    visual_log_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"running step4 for {target.candidate_id} | "
        f"{target.company} / {target.product_name} / {target.product_version}"
    )

    started = time.perf_counter()
    result = map_evidence_for_batch(
        task_package=task_package,
        candidates=[target],
        batch_id=f"single-{target.candidate_id}",
        visual_log_dir=visual_log_dir,
    )
    elapsed = time.perf_counter() - started

    out_path = args.output_dir / f"step4_{target.candidate_id}.json"
    out_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    item = result.results[0]
    print(
        f"\n=== {target.candidate_id} done in {elapsed:.1f}s ==="
        f"\n  launch_date: {item.launch_date or '-'}"
        f"\n  disqualified: {item.disqualified}"
        f"\n  total_score: {item.total_score}"
        f"\n  comparisons: {len(item.comparisons)}"
        f"\n  searched_queries: {len(item.searched_queries)}"
        f"\n  searched_providers: {item.searched_providers}"
        f"\n  output: {out_path}"
    )
    print(f"\n--- per-feature breakdown ---")
    for c in item.comparisons:
        urls = len({e.url for e in c.evidence})
        print(f"  [{c.feature_id}] {c.status} score={c.score} ev_urls={urls}")
        print(f"      patent: {c.patent_feature[:90]}")
        print(f"      compet: {c.competitor_feature[:90] if c.competitor_feature else '-'}")
        print(f"      reason: {c.reasoning[:120]}")


if __name__ == "__main__":
    main()
