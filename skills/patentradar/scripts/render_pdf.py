"""Render a markdown report to PDF using WeasyPrint.

Usage:
    python skills/patentradar/scripts/render_pdf.py <input.md> <output.pdf>

Exit codes:
    0  PDF written successfully
    1  Dependency missing (weasyprint / markdown / system libs)
    2  Bad arguments or input file missing
"""

from __future__ import annotations

import sys
from pathlib import Path

CSS = """
@page { size: A4; margin: 18mm 14mm; }
body { font-family: "PingFang SC", "Helvetica Neue", "Arial", sans-serif;
       font-size: 10.5pt; line-height: 1.55; color: #222; }
h1 { font-size: 19pt; border-bottom: 2px solid #333; padding-bottom: 4pt; margin-top: 0; }
h2 { font-size: 14pt; margin-top: 18pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }
h3 { font-size: 12pt; color: #444; margin-top: 14pt; }
h4, h5 { font-size: 11pt; color: #555; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; table-layout: fixed; }
th, td { border: 1px solid #888; padding: 4pt 6pt; font-size: 9pt;
         vertical-align: top; word-break: normal; overflow-wrap: anywhere; }
th { background: #f0f0f0; }
tr { break-inside: avoid; page-break-inside: avoid; }
a { color: #1a6dba; text-decoration: none; word-break: break-all; }
blockquote { border-left: 3px solid #aaa; padding: 4pt 10pt; color: #555;
             background: #fafafa; margin: 6pt 0; }
code { background: #f3f3f3; padding: 0 3pt; border-radius: 2pt;
       font-family: "Menlo", "Courier New", monospace; font-size: 9.5pt; }
pre code { display: block; padding: 8pt; }
"""


def render(md_path: Path, pdf_path: Path) -> None:
    import markdown
    from weasyprint import HTML

    html_body = markdown.markdown(
        md_path.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code"],
    )
    html_full = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{CSS}</style></head><body>{html_body}</body></html>"
    )
    HTML(string=html_full).write_pdf(pdf_path)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"Usage: python {argv[0]} <input.md> <output.pdf>", file=sys.stderr)
        return 2
    md_path = Path(argv[1])
    pdf_path = Path(argv[2])
    if not md_path.is_file():
        print(f"ERROR: input file not found: {md_path}", file=sys.stderr)
        return 2
    try:
        render(md_path, pdf_path)
    except ImportError as e:
        print(f"ERROR: dependency missing: {e}. Install with: pip install weasyprint markdown", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"ERROR: weasyprint runtime failed (likely missing system libs pango/cairo): {e}", file=sys.stderr)
        return 1
    print(f"OK {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
