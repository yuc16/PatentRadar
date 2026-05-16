"""Command-line entrypoint."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import typer

from patentradar.fetcher.google_patents import normalize_publication_no
from patentradar.llm.stream import install_file_writer_from_env, set_module_label
from patentradar.modules.competitor_search import run_competitor_search
from patentradar.modules.decompose import run_decompose
from patentradar.modules.full_claim_chart import (
    load_task_package,
    load_top_report,
    run_full_claim_chart,
)
from patentradar.modules.report import (
    load_full_claim_chart as load_report_full_claim_chart,
    load_task_package as load_report_task_package,
    run_report,
)

app = typer.Typer(no_args_is_help=True)

_logging_configured = False


def _setup_logging() -> None:
    """Configure root logger so every src-level logger.info(...) reaches stdout.

    The FastAPI runner tees this subprocess's stdout to module_<N>.log, which
    the SSE endpoint then forwards to the dashboard. Without this, all
    `logger.info(...)` calls in src/ are silently dropped (root logger has no
    handler and default level is WARNING).
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    level_name = os.environ.get("PATENTRADAR_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger()
    # Wipe any handler typer/uvicorn may have attached so we don't double-print
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)

    # Tame noisy 3rd-party libraries
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@app.callback()
def callback() -> None:
    """PatentRadar v2 command line."""
    _setup_logging()
    # When PATENTRADAR_STREAM_LOG env is set (typically by the FastAPI runner
    # launching this CLI as a subprocess), register a JSONL writer that
    # captures every LLM token delta. No-op for direct CLI use.
    install_file_writer_from_env()
    label = os.environ.get("PATENTRADAR_MODULE_LABEL")
    if label:
        set_module_label(label)


@app.command("decompose")
def decompose_command(
    publication_no: str,
    output_dir: Path = typer.Option(
        Path("data/output"),
        "--output-dir",
        "-o",
        help="Directory where task_package.json will be written.",
    ),
) -> None:
    target = output_dir / normalize_publication_no(publication_no)
    task_package = run_decompose(publication_no, output_dir=target)
    typer.echo(f"Wrote {target / 'task_package.json'}")
    typer.echo(f"Claims: {len(task_package.claims)}")
    typer.echo(f"Technology tag: {task_package.technology_tag}")


@app.command("competitor-search")
def competitor_search_command(
    task_package: Path = typer.Argument(..., help="Path to module-one task_package.json."),
    output_dir: Path = typer.Option(
        Path("data/output"),
        "--output-dir",
        "-o",
        help="Directory where module-two JSON artifacts will be written.",
    ),
    max_workers: int = typer.Option(3, "--max-workers", help="Parallel evidence workers for step 4."),
) -> None:
    report = run_competitor_search(
        task_package_path=task_package,
        output_dir=output_dir,
        max_workers=max_workers,
    )
    typer.echo(f"Wrote {output_dir / 'step5_top5_claim1_candidates.json'}")
    typer.echo(f"Top candidates: {len(report.top_competitors)}")


@app.command("full-claim-chart")
def full_claim_chart_command(
    task_package: Path = typer.Argument(..., help="Path to module-one task_package.json."),
    top_report: Path = typer.Argument(..., help="Path to module-two step5_top5_claim1_candidates.json."),
    output_dir: Path = typer.Option(
        Path("data/output"),
        "--output-dir",
        "-o",
        help="Directory where module-three JSON artifacts will be written.",
    ),
    max_workers: int = typer.Option(2, "--max-workers", help="Parallel candidate workers."),
) -> None:
    tp = load_task_package(task_package)
    tr = load_top_report(top_report)
    report = run_full_claim_chart(
        task_package=tp,
        top_report=tr,
        output_dir=output_dir,
        max_workers=max_workers,
    )
    typer.echo(f"Wrote {output_dir / 'top5_full_claim_chart.json'}")
    typer.echo(f"Completed candidates: {len(report.top_competitors)} (excluded {len(report.excluded_candidates)})")


@app.command("report")
def report_command(
    task_package: Path = typer.Argument(..., help="Path to module-one task_package.json."),
    full_claim_chart: Path = typer.Argument(..., help="Path to module-three top5_full_claim_chart.json."),
    output_dir: Path = typer.Option(
        Path("data/output"),
        "--output-dir",
        "-o",
        help="Directory where report.md and similar_patents.json will be written.",
    ),
) -> None:
    tp = load_report_task_package(task_package)
    fcr = load_report_full_claim_chart(full_claim_chart)
    report_path = run_report(
        task_package=tp,
        full_claim_chart_report=fcr,
        output_dir=output_dir,
    )
    typer.echo(f"Wrote {report_path}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
