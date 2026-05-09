from __future__ import annotations

import json
import unittest
from pathlib import Path

from patentradar.fetcher.google_patents import fetch_patent, normalize_publication_no
from patentradar.modules.decompose import run_decompose
from patentradar.schemas import TaskPackage

TEST_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = TEST_DIR / "outputs"


class DecomposeTest(unittest.TestCase):
    def test_normalize_publication_no_accepts_common_variants(self) -> None:
        cases = {
            "CN-105335144-B": "CN105335144B",
            "CN 114512759 B": "CN114512759B",
            "https://patents.google.com/patent/CN107423660B/zh": "CN107423660B",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_publication_no(raw), expected)

    def test_google_patents_fetch_generalizes_across_cn_patents(self) -> None:
        payload = json.loads((TEST_DIR / "inputs" / "publications.json").read_text())
        publications = payload["generalization_publications"]

        for publication_no in publications:
            with self.subTest(publication_no=publication_no):
                fetched = fetch_patent(publication_no)
                self.assertEqual(fetched.patent.publication_no, publication_no)
                self.assertTrue(fetched.patent.title)
                self.assertTrue(fetched.patent.google_patents_url.endswith(f"/{publication_no}/zh"))
                self.assertGreaterEqual(len(fetched.claims), 5)
                self.assertEqual(fetched.claims[0].claim_no, 1)
                self.assertTrue(fetched.claims[0].claim_text)

    def test_current_patent_applicants_use_cn_aliases_when_known(self) -> None:
        expectations = {
            "CN105335144B": ["比亚迪股份有限公司"],
            "CN114512759B": ["比亚迪股份有限公司"],
            "CN107423660B": ["比亚迪半导体股份有限公司"],
        }
        for publication_no, applicants in expectations.items():
            with self.subTest(publication_no=publication_no):
                fetched = fetch_patent(publication_no)
                self.assertEqual(fetched.patent.applicants, applicants)

    def test_decompose_end_to_end_publications(self) -> None:
        payload = json.loads((TEST_DIR / "inputs" / "publications.json").read_text())
        expectations = {
            "CN105335144B": {
                "claims_source": "html",
                "min_claims": 12,
                "claim_1_contains": "车辆后备箱自动开启控制系统",
                "technology_tag": "整车与车身底盘",
                "applicants": ["比亚迪股份有限公司"],
            },
            "CN114512759B": {
                "claims_source": "html",
                "min_claims": 10,
                "claim_1_contains": "单体电池",
                "technology_tag": "动力电池",
                "applicants": ["比亚迪股份有限公司"],
            },
            "CN107423660B": {
                "claims_source": "pdf_vision",
                "min_claims": 7,
                "claim_1_contains": "指纹识别装置",
                "technology_tag": "其他",
                "applicants": ["比亚迪半导体股份有限公司"],
            },
        }

        for publication_no in payload["module_one_regression_publications"]:
            with self.subTest(publication_no=publication_no):
                package = run_decompose(publication_no, output_dir=OUTPUT_DIR / publication_no)
                expectation = expectations[publication_no]
                self.assertEqual(package.patent.publication_no, publication_no)
                self.assertEqual(package.claims_source, expectation["claims_source"])
                self.assertEqual(package.patent.applicants, expectation["applicants"])
                self.assertGreaterEqual(len(package.claims), expectation["min_claims"])
                self.assertIn(expectation["claim_1_contains"], package.claim_1_text)
                self.assertGreaterEqual(len(package.claim_1_features), 4)
                self.assertEqual(package.technology_tag, expectation["technology_tag"])
                self.assertNotIn("patent-image-not-available", package.claim_1_text)

                written = OUTPUT_DIR / publication_no / "task_package.json"
                self.assertTrue(written.exists())
                payload = json.loads(written.read_text(encoding="utf-8"))
                TaskPackage.model_validate(payload)
                raw = written.read_text(encoding="utf-8")
                for old_field in (
                    "engineering_terms",
                    "marketing_terms",
                    "is_essential",
                    "is_independent",
                    "depends_on",
                ):
                    self.assertNotIn(old_field, raw)


if __name__ == "__main__":
    unittest.main()
