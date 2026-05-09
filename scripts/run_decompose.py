from __future__ import annotations

import argparse
from pathlib import Path

from patentradar.modules.decompose import run_decompose


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("publication_no")
    parser.add_argument("--output-dir", default="data/output")
    args = parser.parse_args()

    target = Path(args.output_dir) / args.publication_no.upper()
    task_package = run_decompose(args.publication_no, output_dir=target)
    print(target / "task_package.json")
    print(f"claims={len(task_package.claims)} technology_tag={task_package.technology_tag}")


if __name__ == "__main__":
    main()
