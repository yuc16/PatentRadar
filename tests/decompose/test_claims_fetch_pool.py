from __future__ import annotations

import json
import unittest
from pathlib import Path

from patentradar.schemas import Claim, PatentInfo

TEST_DIR = Path(__file__).resolve().parent
INPUT_PATH = TEST_DIR / "inputs" / "full_patent_pool.json"
RESULTS_PATH = TEST_DIR / "results" / "claims_fetch_pool_summary.json"
OUTPUTS_DIR = TEST_DIR / "outputs" / "claims_fetch_pool"


class ClaimsFetchPoolTest(unittest.TestCase):
    def test_full_pool_claims_fetch_results_are_complete(self) -> None:
        publications = json.loads(INPUT_PATH.read_text(encoding="utf-8"))["publications"]
        summary = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

        self.assertEqual(summary["publication_count"], len(publications))
        self.assertEqual(summary["failure_count"], 0, summary.get("failures"))
        self.assertEqual(summary["success_count"], len(publications))

        for publication_no in publications:
            with self.subTest(publication_no=publication_no):
                path = OUTPUTS_DIR / f"{publication_no}.json"
                self.assertTrue(path.exists(), f"missing {path}")
                payload = json.loads(path.read_text(encoding="utf-8"))
                PatentInfo.model_validate(payload["patent"])
                claims = [Claim.model_validate(item) for item in payload["claims"]]
                self.assertGreaterEqual(len(claims), 1)
                self.assertEqual(claims[0].claim_no, 1)
                self.assertTrue(claims[0].claim_text)


if __name__ == "__main__":
    unittest.main()
