"""Module-three test runner.

Example (full TOP5):
  python tests/full_claim_chart/run_full_claim_chart.py \\
    --task-package tests/decompose/outputs/CN114512759B/task_package.json \\
    --top-report   tests/competitor_search/outputs/CN114512759B/step5_top5_claim1_candidates.json \\
    --output-dir   tests/full_claim_chart/outputs/CN114512759B

Single candidate (debug):
  python tests/full_claim_chart/run_full_claim_chart.py \\
    --task-package tests/decompose/outputs/CN114512759B/task_package.json \\
    --top-report   tests/competitor_search/outputs/CN114512759B/step5_top5_claim1_candidates.json \\
    --output-dir   tests/full_claim_chart/outputs/CN114512759B \\
    --candidate-id P01

When `step5_top5_claim1_candidates.json` does not exist (the user has only run
step1-4 so far), pass `--candidate-evidence` pointing to
`step4_candidate_evidence.json` to bootstrap a synthetic TopCompetitorReport.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from patentradar.modules.full_claim_chart import (
    load_task_package,
    load_top_report,
    run_full_claim_chart,
)
from patentradar.schemas import (
    CandidateEvidence,
    FullClaimChartReport,
    TopCompetitorReport,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-package", required=True, type=Path)
    parser.add_argument(
        "--top-report",
        type=Path,
        help="Path to module-two step5_top5_claim1_candidates.json (preferred input).",
    )
    parser.add_argument(
        "--candidate-evidence",
        type=Path,
        help="Fallback: path to step4_candidate_evidence.json if step5 hasn't been run.",
    )
    parser.add_argument(
        "--candidate-id",
        help="If set, process only this candidate (for fast debug).",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=2)
    args = parser.parse_args()

    task_package = load_task_package(args.task_package)
    top_report = _load_input(args)

    if args.candidate_id:
        filtered = [
            c for c in top_report.top_competitors if c.candidate.candidate_id == args.candidate_id
        ]
        if not filtered:
            raise SystemExit(f"candidate {args.candidate_id} not found in top_report")
        top_report = TopCompetitorReport(
            publication_no=top_report.publication_no,
            top_competitors=filtered,
            excluded_candidates=[],
        )

    report: FullClaimChartReport = run_full_claim_chart(
        task_package=task_package,
        top_report=top_report,
        output_dir=args.output_dir,
        max_workers=args.max_workers,
    )

    print(
        json.dumps(
            {
                "publication_no": report.publication_no,
                "completed": len(report.top_competitors),
                "excluded": len(report.excluded_candidates),
                "scores": [
                    {
                        "candidate_id": c.candidate.candidate_id,
                        "total_score": c.total_score,
                        "claim_1_score": c.claim_1_score,
                    }
                    for c in report.top_competitors
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _load_input(args) -> TopCompetitorReport:
    if args.top_report and args.top_report.exists():
        return load_top_report(args.top_report)
    if args.candidate_evidence and args.candidate_evidence.exists():
        # Bootstrap a TopCompetitorReport from step4_candidate_evidence.json so
        # module three can run before module two's step5 is finalized.
        raw = json.loads(args.candidate_evidence.read_text(encoding="utf-8"))
        items = [CandidateEvidence.model_validate(item) for item in raw.get("results", [])]
        valid = [item for item in items if not item.disqualified]
        excluded = [item for item in items if item.disqualified]
        valid.sort(key=lambda i: (i.total_score, i.candidate.candidate_id), reverse=True)
        top = valid[:5]
        return TopCompetitorReport(
            publication_no=raw.get("publication_no", ""),
            top_competitors=top,
            excluded_candidates=excluded,
        )
    raise SystemExit("Either --top-report or --candidate-evidence is required.")


if __name__ == "__main__":
    main()
