"""Real module-two tests.

These tests intentionally call GPT-5.5 and external search APIs when enabled.
Run only when supervising real output:

PATENTRADAR_RUN_REAL_COMPETITOR_TESTS=1 \
uv run python -m unittest tests.competitor_search.test_competitor_search
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from patentradar.modules.competitor_search.pipeline import (
    load_task_package,
    run_step1_generate_queries,
    run_step2_search_results,
    run_step3_filter_candidates,
    run_step4_map_evidence,
    run_step5_rank_top,
)


class CompetitorSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.getenv("PATENTRADAR_RUN_REAL_COMPETITOR_TESTS") != "1":
            self.skipTest("real GPT/search test is opt-in")
        self.task_path = Path(
            os.getenv(
                "PATENTRADAR_TEST_TASK_PACKAGE",
                "tests/decompose/outputs/CN114512759B/task_package.json",
            )
        )
        self.output_dir = Path("tests/competitor_search/outputs/CN114512759B")
        self.task_package = load_task_package(self.task_path)

    def test_module_two_all_steps_cn114512759b(self) -> None:
        query_plan = run_step1_generate_queries(
            task_package=self.task_package,
            output_dir=self.output_dir,
        )
        self.assertGreaterEqual(len(query_plan.queries), 30)
        self.assertLessEqual(len(query_plan.queries), 50)

        search_results = run_step2_search_results(
            task_package=self.task_package,
            query_plan=query_plan,
            output_dir=self.output_dir,
        )
        self.assertGreaterEqual(len(search_results.results), 1)

        shortlist = run_step3_filter_candidates(
            task_package=self.task_package,
            search_results=search_results,
            output_dir=self.output_dir,
        )
        self.assertGreaterEqual(len(shortlist.candidates), 15)
        self.assertLessEqual(len(shortlist.candidates), 30)

        evidence_results = run_step4_map_evidence(
            task_package=self.task_package,
            shortlist=shortlist,
            output_dir=self.output_dir,
            max_workers=3,
        )
        self.assertEqual(len(evidence_results), len(shortlist.candidates))

        report = run_step5_rank_top(
            task_package=self.task_package,
            evidence_results=evidence_results,
            output_dir=self.output_dir,
        )
        self.assertLessEqual(len(report.top_competitors), len(evidence_results))


if __name__ == "__main__":
    unittest.main()
