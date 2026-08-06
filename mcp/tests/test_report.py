from pathlib import Path

from patentradar_mcp.report import render_report


def test_render_report_creates_markdown_and_pdf(tmp_path: Path) -> None:
    markdown_text = "## 1. 专利详细信息\n\n" + ("公开证据显示需要继续人工复核，不构成法律意见。" * 20)
    md_path, pdf_path = render_report(
        publication_no="CN114512759B",
        markdown_text=markdown_text,
        output_dir=tmp_path,
    )

    assert md_path.read_text(encoding="utf-8").startswith("## 1. 专利详细信息")
    assert pdf_path.read_bytes().startswith(b"%PDF")
