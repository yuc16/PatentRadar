"""Module-four test runner.

Example:
  python tests/report/run_report.py \\
    --task-package tests/decompose/outputs/CN114512759B/task_package.json \\
    --full-claim-chart tests/full_claim_chart/outputs/CN114512759B/top5_full_claim_chart.json \\
    --output-dir tests/report/outputs/CN114512759B
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from patentradar.modules.report import (
    load_full_claim_chart,
    load_task_package,
    run_report,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-package", required=True, type=Path)
    parser.add_argument("--full-claim-chart", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    tp = load_task_package(args.task_package)
    fcr = load_full_claim_chart(args.full_claim_chart)
    report_path = run_report(
        task_package=tp,
        full_claim_chart_report=fcr,
        output_dir=args.output_dir,
    )
    print(f"\nReport written to: {report_path}")


if __name__ == "__main__":
    main()
