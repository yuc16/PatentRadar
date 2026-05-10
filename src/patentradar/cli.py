"""Command-line entrypoint."""

from __future__ import annotations

from pathlib import Path

import typer

from patentradar.fetcher.google_patents import normalize_publication_no
from patentradar.modules.competitor_search import run_competitor_search
from patentradar.modules.decompose import run_decompose

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """PatentRadar v2 command line."""


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
