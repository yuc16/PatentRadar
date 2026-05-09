from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

from patentradar.fetcher.google_patents import fetch_patent

TEST_DIR = Path(__file__).resolve().parent
INPUT_PATH = TEST_DIR / "inputs" / "full_patent_pool.json"
RESULTS_DIR = TEST_DIR / "results"
OUTPUTS_DIR = TEST_DIR / "outputs" / "claims_fetch_pool"


def main() -> int:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    publications: list[str] = payload["publications"]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    started = time.time()
    rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    for index, publication_no in enumerate(publications, start=1):
        print(f"[{index}/{len(publications)}] {publication_no}", flush=True)
        row: dict[str, object] = {
            "publication_no": publication_no,
            "ok": False,
            "claim_count": 0,
            "has_claim_image_placeholders": False,
            "title": "",
            "applicants": "",
            "error_type": "",
            "error": "",
        }
        try:
            fetched = fetch_patent(publication_no)
            row.update(
                {
                    "ok": True,
                    "claim_count": len(fetched.claims),
                    "has_claim_image_placeholders": fetched.has_claim_image_placeholders,
                    "title": fetched.patent.title,
                    "applicants": "; ".join(fetched.patent.applicants),
                }
            )
            claim_payload = {
                "patent": fetched.patent.model_dump(),
                "has_claim_image_placeholders": fetched.has_claim_image_placeholders,
                "claims": [claim.model_dump() for claim in fetched.claims],
            }
            (OUTPUTS_DIR / f"{publication_no}.json").write_text(
                json.dumps(claim_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            row.update({"error_type": exc.__class__.__name__, "error": str(exc)})
            failures.append(row.copy())
        rows.append(row)

    elapsed_seconds = round(time.time() - started, 3)
    summary = {
        "source_file": payload.get("source_file", ""),
        "publication_count": len(publications),
        "success_count": sum(1 for row in rows if row["ok"]),
        "failure_count": sum(1 for row in rows if not row["ok"]),
        "elapsed_seconds": elapsed_seconds,
        "failures": failures,
    }
    (RESULTS_DIR / "claims_fetch_pool_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_path = RESULTS_DIR / "claims_fetch_pool_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["failure_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
