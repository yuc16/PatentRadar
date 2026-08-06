from __future__ import annotations

from pathlib import Path

import markdown
import nh3
from weasyprint import HTML


REPORT_CSS = """
@page { size: A4; margin: 18mm 14mm; }
body { font-family: "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", "Arial", sans-serif;
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


def render_report(*, publication_no: str, markdown_text: str, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(character for character in publication_no if character.isalnum())
    md_path = output_dir / f"{safe_name}.md"
    pdf_path = output_dir / f"{safe_name}.pdf"
    full_markdown = markdown_text.strip() + "\n"
    md_path.write_text(full_markdown, encoding="utf-8")
    raw_html = markdown.markdown(
        full_markdown,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    clean_html = nh3.clean(
        raw_html,
        tags={"h1", "h2", "h3", "h4", "h5", "p", "a", "strong", "em", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "blockquote", "pre", "code", "hr", "br"},
        attributes={
            "a": {"href", "title"},
            "td": {"rowspan", "colspan"},
            "th": {"rowspan", "colspan"},
        },
        url_schemes={"http", "https"},
    )
    document = f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>{REPORT_CSS}</style></head><body>{clean_html}</body></html>"
    HTML(string=document).write_pdf(pdf_path)
    return md_path, pdf_path
