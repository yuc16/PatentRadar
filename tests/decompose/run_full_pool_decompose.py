"""Module-one full-pool end-to-end runner.

Runs `run_decompose` for every publication listed in
`tests/decompose/inputs/full_patent_pool.json` and writes:
- `tests/decompose/outputs/<pub>/task_package.json`
- `tests/decompose/results/full_pool_e2e_summary.json`
- `tests/decompose/results/full_pool_e2e_results.csv`
- `tests/decompose/results/full_pool_e2e.log`

Resumable: skips publications whose `task_package.json` already exists.
On ChatGPT quota / rate-limit errors it sleeps and retries (up to MAX_QUOTA_RETRIES).
"""

from __future__ import annotations

import csv
import json
import logging
import sys
import time
import traceback
from pathlib import Path

from patentradar.modules.decompose import run_decompose

ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "inputs" / "full_patent_pool.json"
OUTPUTS_DIR = ROOT / "outputs"
RESULTS_DIR = ROOT / "results"
SUMMARY_PATH = RESULTS_DIR / "full_pool_e2e_summary.json"
CSV_PATH = RESULTS_DIR / "full_pool_e2e_results.csv"
LOG_PATH = RESULTS_DIR / "full_pool_e2e.log"

MAX_QUOTA_RETRIES = 12  # ~6 hours of cooling at 30min each, then give up on this pub
QUOTA_SLEEP_SECONDS = 1800
INTER_PATENT_PAUSE_SECONDS = 2

QUOTA_KEYWORDS = ("quota", "rate limit", "429", "限流", "配额", "too many requests")


def is_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(key in msg for key in QUOTA_KEYWORDS)


def setup_logger() -> logging.Logger:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("full_pool_e2e")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.handlers = [fh, sh]
    return logger


def existing_summary() -> dict:
    if SUMMARY_PATH.exists():
        try:
            return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"rows": []}


def write_summary(rows: list[dict], publications: list[str], started_at: str) -> None:
    success = sum(1 for r in rows if r["ok"])
    failure = sum(1 for r in rows if not r["ok"])
    summary = {
        "input_file": str(INPUT_PATH),
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "publication_count": len(publications),
        "completed_count": len(rows),
        "success_count": success,
        "failure_count": failure,
        "rows": rows,
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if rows:
        with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def run_one(pub: str, logger: logging.Logger) -> dict:
    out_dir = OUTPUTS_DIR / pub
    target = out_dir / "task_package.json"
    if target.exists():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            return {
                "publication_no": pub,
                "ok": True,
                "skipped": True,
                "claims_source": payload.get("claims_source", ""),
                "claim_count": len(payload.get("claims", [])),
                "feature_count": sum(len(c.get("features", [])) for c in payload.get("claims", [])),
                "technology_tag": payload.get("technology_tag", ""),
                "applicants": "; ".join(payload.get("patent", {}).get("applicants", []) or []),
                "elapsed_s": 0.0,
                "error_type": "",
                "error": "",
            }
        except (OSError, json.JSONDecodeError):
            pass

    quota_attempts = 0
    while True:
        try:
            started = time.perf_counter()
            pkg = run_decompose(pub, output_dir=out_dir)
            elapsed = time.perf_counter() - started
            return {
                "publication_no": pub,
                "ok": True,
                "skipped": False,
                "claims_source": pkg.claims_source,
                "claim_count": len(pkg.claims),
                "feature_count": sum(len(c.features) for c in pkg.claims),
                "technology_tag": pkg.technology_tag,
                "applicants": "; ".join(pkg.patent.applicants),
                "elapsed_s": round(elapsed, 2),
                "error_type": "",
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            if is_quota_error(exc) and quota_attempts < MAX_QUOTA_RETRIES:
                quota_attempts += 1
                logger.warning(
                    "%s quota/rate hit (attempt %d/%d): %s — sleeping %ds",
                    pub,
                    quota_attempts,
                    MAX_QUOTA_RETRIES,
                    str(exc)[:200],
                    QUOTA_SLEEP_SECONDS,
                )
                time.sleep(QUOTA_SLEEP_SECONDS)
                continue
            logger.error("%s FAILED %s: %s\n%s", pub, type(exc).__name__, exc, traceback.format_exc())
            return {
                "publication_no": pub,
                "ok": False,
                "skipped": False,
                "claims_source": "",
                "claim_count": 0,
                "feature_count": 0,
                "technology_tag": "",
                "applicants": "",
                "elapsed_s": 0.0,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }


def main() -> int:
    logger = setup_logger()
    publications: list[str] = json.loads(INPUT_PATH.read_text(encoding="utf-8"))["publications"]
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    prior = {row["publication_no"]: row for row in existing_summary().get("rows", [])}
    rows: list[dict] = []
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    logger.info("starting full pool e2e total=%d", len(publications))

    for index, pub in enumerate(publications, start=1):
        logger.info("[%d/%d] %s start", index, len(publications), pub)
        row = run_one(pub, logger)
        rows.append(row)
        # Persist incrementally so partial progress is never lost.
        merged = {**prior, **{r["publication_no"]: r for r in rows}}
        write_summary(list(merged.values()), publications, started_at)

        if row["ok"]:
            logger.info(
                "[%d/%d] %s OK %s claims=%d features=%d tag=%s elapsed=%.2fs%s",
                index,
                len(publications),
                pub,
                row["claims_source"] or "skipped",
                row["claim_count"],
                row["feature_count"],
                row["technology_tag"] or "-",
                row["elapsed_s"],
                " (cached)" if row["skipped"] else "",
            )
        else:
            logger.error(
                "[%d/%d] %s FAIL %s: %s",
                index,
                len(publications),
                pub,
                row["error_type"],
                row["error"],
            )
        # Gentle pacing to avoid hammering Codex.
        if not row["skipped"]:
            time.sleep(INTER_PATENT_PAUSE_SECONDS)

    success = sum(1 for r in rows if r["ok"])
    logger.info("done success=%d/%d", success, len(publications))
    return 0 if success == len(publications) else 1


if __name__ == "__main__":
    sys.exit(main())
