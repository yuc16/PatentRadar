"""Module-one pipeline."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.fetcher.google_patents import fetch_patent
from patentradar.fetcher.pdf import download_pdf, render_claim_pages
from patentradar.llm import get_llm_provider
from patentradar.llm.workers.decompose_worker import decompose_claims
from patentradar.schemas import TaskPackage

logger = logging.getLogger(__name__)


def run_decompose(
    publication_no: str,
    *,
    output_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> TaskPackage:
    started = time.perf_counter()
    fetched = fetch_patent(publication_no)
    images: list[bytes] | None = None
    source = "html"
    if fetched.has_claim_image_placeholders:
        provider = get_llm_provider()
        if not provider.supports_vision:
            message = (
                f"[decompose] HTML 中检测到图片/公式占位，但当前 LLM provider "
                f"`{provider.name}` 未开启 vision 支持，已跳过 PDF Vision 还原步骤；"
                f"输出的 claim_text 将保留 HTML 原文（含占位符），下游模块可能"
                f"在含公式/图示的条款上找不到证据。如需启用 PDF Vision，请把 "
                f"PATENTRADAR_LLM_BACKEND 切回 codex，或在 OpenAI 兼容侧选支持 "
                f"vision 的模型并设置 PATENTRADAR_OPENAI_VISION=true。"
            )
            logger.warning(message)
            sys.stderr.write(message + "\n")
        else:
            logger.info(
                "decompose PDF vision triggered publication_no=%s claim_count=%d pdf_url=%s",
                fetched.patent.publication_no,
                len(fetched.claims),
                bool(fetched.patent.pdf_url),
            )
            pdf_bytes = download_pdf(fetched.patent.pdf_url)
            images = render_claim_pages(pdf_bytes)
            source = "pdf_vision"

    task_package = decompose_claims(
        patent=fetched.patent,
        html_claims=fetched.claims,
        images=images,
        source=source,
        model=model,
        reasoning_effort=reasoning_effort,
    )

    if output_dir is not None:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "task_package.json").write_text(
            task_package.model_dump_json(ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "decompose completed publication_no=%s source=%s claim_count=%d technology_tag=%s elapsed_ms=%d",
        task_package.patent.publication_no,
        task_package.claims_source,
        len(task_package.claims),
        task_package.technology_tag,
        elapsed_ms,
    )
    return task_package
