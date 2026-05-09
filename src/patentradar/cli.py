"""Command-line entrypoint."""

from __future__ import annotations

from pathlib import Path

import typer

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
    target = output_dir / publication_no.upper()
    task_package = run_decompose(publication_no, output_dir=target)
    typer.echo(f"Wrote {target / 'task_package.json'}")
    typer.echo(f"Claims: {len(task_package.claims)}")
    typer.echo(f"Technology tag: {task_package.technology_tag}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
