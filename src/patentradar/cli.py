"""PatentRadar CLI 入口。"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

_SH = ZoneInfo("Asia/Shanghai")

from . import config
from .agents import SearchAgent, get_perspective
from .patent import vision
from .patent.decomposer import decompose
from .patent.fetcher import fetch_patent
from .report import render_markdown
from .reviewer import review_agent_outputs
from .schemas import AgentOutput, FinalReport, TaskPackage
from .search.session import SearchSession

app = typer.Typer(add_completion=False, help="PatentRadar v1 - 专利侵权线索挖掘系统")
console = Console()


_RUN_MARKER_NAME = ".current_run_dir"


def _get_or_create_run_dir(pub_no: str) -> Path:
    """返回当前 pub_no 的"工作流目录"。

    - 默认续用 ``tmp/<pub>/.current_run_dir`` 中记录的目录（一组 4 个命令
      自然归档到同一个 ``runs/<YYYYMMDD_HHMMSS>/`` 下）。
    - 设置环境变量 ``PATENTRADAR_NEW_RUN=1`` 强制新建。
    - 若 marker 文件存在但目录已被删，自动新建。
    """
    cfg = config
    marker = cfg.INTERMEDIATE_DIR / pub_no / _RUN_MARKER_NAME
    force_new = os.getenv("PATENTRADAR_NEW_RUN", "").strip().lower() in {"1", "true", "yes"}
    if not force_new and marker.exists():
        try:
            existing = Path(marker.read_text(encoding="utf-8").strip())
            if existing.is_dir():
                return existing
        except OSError:
            pass
    # 新建
    now_sh = datetime.now(_SH)
    run_dir = cfg.OUTPUT_DIR / pub_no / "runs" / now_sh.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(run_dir), encoding="utf-8")
    return run_dir


def _setup_logging(
    verbosity: int = 1,
    *,
    pub_no: str | None = None,
    cmd: str | None = None,
) -> Path | None:
    """配置日志输出。verbosity: 0=WARNING, 1=INFO, 2=DEBUG。

    若给定 ``pub_no`` 和 ``cmd``：
      - 同时把 logger 输出落盘到 ``output/<pub_no>/runs/<TS>_<cmd>.log``
      - 同时 patch ``console.print`` / ``console.rule`` / ``console.status``，
        让所有 CLI 状态打印也镜像到日志文件（plain text，无 ANSI）
    """
    level = {0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG)
    handlers: list[logging.Handler] = [
        RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            show_level=False,
            markup=False,
            log_time_format="%H:%M:%S",
        )
    ]
    log_file: Path | None = None
    if pub_no and cmd:
        run_dir = _get_or_create_run_dir(pub_no)
        log_file = run_dir / f"{cmd}.log"
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s | %(message)s"))
        handlers.append(fh)

    logging.basicConfig(
        level=level,
        format="%(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # 让 console.print / console.rule 同时镜像到 log_file
    if log_file is not None:
        _mirror_console_to_file(log_file)
    return log_file


def _mirror_console_to_file(log_file: Path) -> None:
    """让 ``console.print`` 同时镜像到 ``log_file``（plain text，无 ANSI）。

    Rich 的 ``console.rule`` / ``status`` 等内部都调 ``console.print``，
    所以只 patch ``print`` 即可让所有渲染都被镜像；不要 patch 高阶方法（会双写）。

    重复调用幂等：第二次调用换新文件。
    """
    if not getattr(console, "_orig_print", None):
        console._orig_print = console.print  # type: ignore[attr-defined]

    # 关闭旧文件 console（如有）
    old_fc = getattr(console, "_file_console", None)
    if old_fc is not None:
        try:
            old_fc.file.close()
        except Exception:  # noqa: BLE001
            pass

    log_fh = open(log_file, "a", encoding="utf-8")
    file_console = Console(file=log_fh, force_terminal=False, no_color=True, width=120)
    console._file_console = file_console  # type: ignore[attr-defined]

    orig_print = console._orig_print  # type: ignore[attr-defined]

    def patched_print(*args, **kwargs):
        orig_print(*args, **kwargs)
        try:
            file_console.print(*args, **kwargs)
        except Exception:  # noqa: BLE001
            pass

    console.print = patched_print  # type: ignore[assignment]


_decompose_logger = logging.getLogger("patentradar.decompose")


def _decompose_one(
    pub_no: str,
    *,
    reasoning_effort: Optional[str] = None,
    force_vision: bool = False,
    log: bool = True,
) -> tuple[TaskPackage, list]:
    """单个专利：抓取 → 按需视觉 → GPT-5.5 拆解。"""
    import time as _time

    reasoning_effort = reasoning_effort or config.DECOMPOSER_REASONING_EFFORT
    model = (os.getenv("REVIEWER_MODEL") or "gpt-5.5").strip()

    _decompose_logger.info("DECOMPOSE START patent=%s model=%s reasoning=%s", pub_no, model, reasoning_effort)
    t0 = _time.monotonic()
    fr = fetch_patent(pub_no)
    _decompose_logger.info(
        "DECOMPOSE FETCHED title=%r assignees=%s claim_1_chars=%d formula_loss=%s pdf_url=%s",
        fr.meta.title, fr.meta.assignees, len(fr.claim_1_text or ""),
        fr.has_formula_loss, bool(fr.pdf_url),
    )

    need_vision = force_vision or fr.has_formula_loss
    if log:
        console.print(
            f"  公式残缺标记: {'是' if fr.has_formula_loss else '否'}  "
            f"→ 路径: [{'magenta' if need_vision else 'green'}]"
            f"{'多模态(含 PDF 视觉)' if need_vision else '纯文本'}[/]"
        )

    images: list[bytes] | None = None
    if need_vision:
        if not fr.pdf_url:
            raise RuntimeError(f"需要视觉路径但未发现 PDF 直链: {pub_no}")
        pdf_bytes = vision.download_pdf(fr.pdf_url)
        images = vision.render_claims_pages(pdf_bytes)
        if not images:
            raise RuntimeError(f"PDF 中未定位到权利要求书页: {pub_no}")
        _decompose_logger.info("DECOMPOSE VISION pages=%d pdf_bytes=%d", len(images), len(pdf_bytes))
        if log:
            console.print(f"  渲染权要书页: {len(images)} 页")

    _decompose_logger.info(
        "DECOMPOSE GPT-5.5 LLM START path=%s",
        "vision_pdf" if need_vision else "html_text",
    )
    t_llm = _time.monotonic()
    claim_1_text, features, industry_tag = decompose(
        pub_no=fr.meta.publication_no,
        title=fr.meta.title,
        claim_1_html=fr.claim_1_text,
        images=images,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    elapsed_llm = round(_time.monotonic() - t_llm, 2)
    _decompose_logger.info(
        "DECOMPOSE GPT-5.5 LLM DONE elapsed=%.2fs n_features=%d industry_tag=%s claim_1_final_chars=%d",
        elapsed_llm, len(features), industry_tag, len(claim_1_text),
    )
    for f in features:
        _decompose_logger.info(
            "  %s%s: %s",
            f.feature_id,
            "" if f.is_essential else " (non-essential)",
            f.feature_text[:120] + ("…" if len(f.feature_text) > 120 else ""),
        )

    pkg = TaskPackage(
        patent=fr.meta,
        claim_1_text=claim_1_text,
        claim_1_text_html=fr.claim_1_text,
        claim_1_source="vision_pdf" if need_vision else "html",
        claim_features=features,
        industry_tag=industry_tag,
        decomposer_model=f"codex:{model}",
        pdf_url=fr.pdf_url,
    )
    _decompose_logger.info("DECOMPOSE DONE total_elapsed=%.2fs", _time.monotonic() - t0)
    return pkg, features


def _log_cached_task_package(task: TaskPackage, source_path: Path) -> None:
    """在 find-competitors-all / review 启动时调用：把缓存中拆解成果写进 log。

    这样即使本次没有触发 GPT-5.5 拆解（因 ``task_package.json`` 已存在），
    log 文件里也能完整看到上游的权要拆解结果，便于追溯。
    """
    _decompose_logger.info(
        "DECOMPOSE CACHED  source=%s  decomposer_model=%s  industry_tag=%s",
        source_path.name, task.decomposer_model, task.industry_tag,
    )
    _decompose_logger.info(
        "DECOMPOSE CACHED  patent=%s title=%r assignees=%s claim_1_source=%s n_features=%d",
        task.patent.publication_no, task.patent.title, task.patent.assignees,
        task.claim_1_source, len(task.claim_features),
    )
    for f in task.claim_features:
        _decompose_logger.info(
            "  %s%s: %s",
            f.feature_id,
            "" if f.is_essential else " (non-essential)",
            f.feature_text[:120] + ("…" if len(f.feature_text) > 120 else ""),
        )


@app.command("decompose")
def decompose_cmd(
    pub_no: str = typer.Argument(..., help="中文专利公开号，例如 CN107423660B"),
    out_dir: Optional[Path] = typer.Option(None, "--out", help="输出目录，默认 output/<pub_no>"),
    print_only: bool = typer.Option(False, "--print-only", help="只打印不写文件"),
    reasoning: Optional[str] = typer.Option(None, "--reasoning", help="GPT-5.5 推理强度: low|medium|high；不传则用 .env 默认"),
    force_vision: bool = typer.Option(False, "--force-vision", help="强制走视觉路径（即使没有公式残缺）"),
    verbose: int = typer.Option(1, "--verbose", "-v", count=True, help="日志级别"),
) -> None:
    """阶段 1：抓取 → 按需视觉 → GPT-5.5 拆解 → task_package.json。"""
    log_file = _setup_logging(verbose, pub_no=pub_no.strip().upper(), cmd="decompose")
    model = (os.getenv("REVIEWER_MODEL") or "gpt-5.5").strip()
    eff = reasoning or config.DECOMPOSER_REASONING_EFFORT
    console.print(f"[cyan]→ 拆解器:[/] codex / model={model}  reasoning={eff}")
    if log_file:
        console.print(f"[dim]日志: {log_file}[/]")

    console.print(f"[cyan]→ 抓取 Google Patents:[/] {pub_no}")
    pkg, features = _decompose_one(
        pub_no.strip().upper(),
        reasoning_effort=reasoning,
        force_vision=force_vision,
    )
    console.print(
        f"  标题: {pkg.patent.title}\n"
        f"  专利权人: {', '.join(pkg.patent.assignees) or '(未知)'}\n"
        f"  HTML 草稿长度: {len(pkg.claim_1_text_html or '')} 字符\n"
        f"  最终版长度: {len(pkg.claim_1_text)} 字符\n"
        f"  来源: [bold]{pkg.claim_1_source}[/]"
    )

    _print_features(pkg.patent.publication_no, pkg.claim_1_text, features)

    if print_only:
        return
    target_dir = out_dir or (config.INTERMEDIATE_DIR / pkg.patent.publication_no)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / "task_package.json"
    out_path.write_text(
        json.dumps(pkg.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]✓ 已写入:[/] {out_path}")


@app.command("decompose-batch")
def decompose_batch_cmd(
    xlsx: Path = typer.Argument(..., help="包含专利公开号的 xlsx，单列、首行表头"),
    limit: int = typer.Option(0, "--limit", help="仅处理前 N 条；0 表示全部"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--no-skip-existing"),
    reasoning: Optional[str] = typer.Option(None, "--reasoning", help="不传则用 .env 默认"),
    log_path: Optional[Path] = typer.Option(None, "--log", help="将每条结果同时写入 jsonl 日志"),
    verbose: int = typer.Option(1, "--verbose", "-v", count=True, help="日志级别"),
) -> None:
    """阶段 1 批量：读 xlsx 中所有专利号，依次拆解。"""
    _setup_logging(verbose)
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb.active
    nos: list[str] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row and row[0]:
            nos.append(str(row[0]).strip().upper())
    if limit > 0:
        nos = nos[:limit]
    console.print(f"[cyan]读取到 {len(nos)} 个专利号[/]")

    log_fp = open(log_path, "a", encoding="utf-8") if log_path else None

    ok, fail, vision_used = 0, 0, 0
    for i, pub_no in enumerate(nos, start=1):
        console.rule(f"[{i}/{len(nos)}] {pub_no}")
        target_dir = config.INTERMEDIATE_DIR / pub_no
        out_path = target_dir / "task_package.json"
        if skip_existing and out_path.exists():
            console.print(f"[yellow]已存在，跳过:[/] {out_path}")
            ok += 1
            continue
        try:
            pkg, features = _decompose_one(pub_no, reasoning_effort=reasoning)
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(pkg.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            console.print(
                f"[green]✓[/] {pub_no} "
                f"→ {len(features)} 个特征 (来源={pkg.claim_1_source})"
            )
            ok += 1
            if pkg.claim_1_source == "vision_pdf":
                vision_used += 1
            if log_fp is not None:
                log_fp.write(json.dumps({
                    "i": i,
                    "pub_no": pub_no,
                    "ok": True,
                    "n_features": len(features),
                    "claim_1_source": pkg.claim_1_source,
                    "title": pkg.patent.title,
                }, ensure_ascii=False) + "\n")
                log_fp.flush()
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]✗ 失败:[/] {pub_no} - {e}")
            fail += 1
            if log_fp is not None:
                log_fp.write(json.dumps({
                    "i": i,
                    "pub_no": pub_no,
                    "ok": False,
                    "error": str(e),
                }, ensure_ascii=False) + "\n")
                log_fp.flush()

    if log_fp is not None:
        log_fp.close()

    console.rule("汇总")
    console.print(
        f"成功: [green]{ok}[/]  失败: [red]{fail}[/]  "
        f"视觉路径占用: [magenta]{vision_used}[/]"
    )


@app.command("find-competitors-all")
def find_competitors_all_cmd(
    pub_no: str = typer.Argument(..., help="专利公开号"),
    agents: str = typer.Option(
        "deepseek,kimi,glm",
        "--agents",
        help="逗号分隔的 agent 列表，默认 3 个全跑",
    ),
    out_dir: Optional[Path] = typer.Option(None, "--out"),
    sequential: bool = typer.Option(
        False, "--sequential", help="串行执行（默认并行）"
    ),
    force: bool = typer.Option(
        False, "--force", help="强制重跑所有 agent（默认 agent_*.json 已存在则跳过）"
    ),
    verbose: int = typer.Option(1, "--verbose", "-v", count=True),
) -> None:
    """阶段 3：三 Agent 并行 → agent_outputs.json。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pub_no = pub_no.strip().upper()
    log_file = _setup_logging(verbose, pub_no=pub_no, cmd="find-competitors-all")
    target_dir = out_dir or (config.INTERMEDIATE_DIR / pub_no)
    task_path = target_dir / "task_package.json"
    if not task_path.exists():
        console.print(
            f"[red]task_package.json 不存在:[/] {task_path}\n"
            f"请先运行: [yellow]uv run patentradar decompose {pub_no}[/]"
        )
        raise typer.Exit(2)

    task = TaskPackage.model_validate_json(task_path.read_text(encoding="utf-8"))
    _log_cached_task_package(task, task_path)
    agent_names = [a.strip().lower() for a in agents.split(",") if a.strip()]

    console.rule(f"[cyan]三 Agent 并行 · patent {pub_no}[/]")
    console.print(f"agents: {agent_names}  mode: {'sequential' if sequential else 'parallel'}  force={force}")
    if log_file:
        console.print(f"[dim]日志: {log_file}[/]")

    target_dir.mkdir(parents=True, exist_ok=True)
    search_session = SearchSession(target_dir)

    # 缓存判断：默认 agent_<n>.json 存在就跳过该 Agent
    todo: list[str] = []
    cached: dict[str, AgentOutput] = {}
    for n in agent_names:
        p = target_dir / f"agent_{n}.json"
        if p.exists() and not force:
            cached[n] = AgentOutput.model_validate_json(p.read_text(encoding="utf-8"))
            console.print(f"[yellow]✓ {n} 已存在，跳过[/]（用 --force 强制重跑）")
        else:
            todo.append(n)

    def _run_one(name: str):
        persp = get_perspective(name)
        agent = SearchAgent(persp, search_session=search_session)
        return name, agent.run(task)

    results: dict[str, AgentOutput] = dict(cached)
    errors: dict[str, str] = {}

    if todo:
        if sequential:
            for n in todo:
                try:
                    _, out = _run_one(n)
                    results[n] = out
                except Exception as exc:  # noqa: BLE001
                    errors[n] = str(exc)
                    console.print(f"[red]✗ {n} FAIL:[/] {exc}")
        else:
            with ThreadPoolExecutor(max_workers=len(todo)) as ex:
                futs = {ex.submit(_run_one, n): n for n in todo}
                for fut in as_completed(futs):
                    n = futs[fut]
                    try:
                        _, out = fut.result()
                        results[n] = out
                    except Exception as exc:  # noqa: BLE001
                        errors[n] = str(exc)
                        console.print(f"[red]✗ {n} FAIL:[/] {exc}")

    # 新跑的 Agent 单独写 JSON（缓存的不重写）
    for n in todo:
        if n in results:
            p = target_dir / f"agent_{n}.json"
            p.write_text(
                json.dumps(results[n].model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # 合并 agent_outputs.json
    aggregate = {
        "patent_publication_no": pub_no,
        "agent_outputs": [
            results[n].model_dump()
            for n in agent_names
            if n in results
        ],
        "errors": errors,
    }
    out_path = target_dir / "agent_outputs.json"
    out_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 汇总展示
    console.rule("各 Agent 结果汇总")
    table = Table(show_lines=True)
    table.add_column("Agent", style="cyan")
    table.add_column("耗时(s)", justify="right")
    table.add_column("queries")
    table.add_column("Top")
    table.add_column("公司 / 产品（前 5）")
    for n in agent_names:
        if n not in results:
            table.add_row(n, "-", "-", "-", f"[red]FAIL[/]: {errors.get(n,'?')[:60]}")
            continue
        out = results[n]
        sample = "\n".join(
            f"  {c.rank}. {c.company} / {c.product[:30]} (score={c.score})"
            for c in out.top5_candidates[:5]
        ) or "(无)"
        table.add_row(
            n,
            f"{out.elapsed_seconds}",
            str(len(out.queries_used)),
            str(len(out.top5_candidates)),
            sample,
        )
    console.print(table)
    console.print(f"\n[green]✓ 已写入:[/] {out_path}")


@app.command("report")
def report_cmd(
    pub_no: str = typer.Argument(..., help="专利公开号；要求 review 已跑过"),
    intermediate: Optional[Path] = typer.Option(
        None, "--intermediate", help="中间产物目录，默认 data/intermediate/<pub_no>"
    ),
    out_dir: Optional[Path] = typer.Option(
        None, "--out", help="最终报告目录，默认 output/<pub_no>"
    ),
    verbose: int = typer.Option(1, "--verbose", "-v", count=True),
) -> None:
    """阶段 5：把 final_report.json 渲染为 Markdown。

    写两份：
    - ``output/<pub>/runs/<YYYYMMDD>/<HHMMSS>_report/final_report.md`` —— 历史副本，与本次 run 的 log 同目录，永不被覆盖
    - ``output/<pub>/final_report.md`` —— 最新一份的快捷副本，方便引用
    """
    pub_no = pub_no.strip().upper()
    log_file = _setup_logging(verbose, pub_no=pub_no, cmd="report")
    inter = intermediate or (config.INTERMEDIATE_DIR / pub_no)
    target = out_dir or (config.OUTPUT_DIR / pub_no)

    required = {
        "task_package.json": inter / "task_package.json",
        "final_report.json": inter / "final_report.json",
    }
    missing = [k for k, p in required.items() if not p.exists()]
    if missing:
        console.print(
            f"[red]缺失中间产物:[/] {missing}\n"
            f"请按顺序运行: decompose → find-competitors-all → review"
        )
        raise typer.Exit(2)

    task = TaskPackage.model_validate_json(required["task_package.json"].read_text(encoding="utf-8"))
    _log_cached_task_package(task, required["task_package.json"])
    final = FinalReport.model_validate_json(required["final_report.json"].read_text(encoding="utf-8"))

    agent_outputs: list[AgentOutput] = []
    for n in ("deepseek", "kimi", "glm"):
        p = inter / f"agent_{n}.json"
        if p.exists():
            agent_outputs.append(AgentOutput.model_validate_json(p.read_text(encoding="utf-8")))

    md = render_markdown(task=task, agent_outputs=agent_outputs, final=final)
    target.mkdir(parents=True, exist_ok=True)
    latest_path = target / "final_report.md"
    latest_path.write_text(md, encoding="utf-8")

    # 工作流副本：写到本次 RUN_DIR（与 4 份 log 同目录），跨 run 互不覆盖
    archived_path: Path | None = None
    if log_file is not None:
        archived_path = log_file.parent / "final_report.md"
        archived_path.write_text(md, encoding="utf-8")

    console.rule(f"Markdown 报告生成完成 — {pub_no}")
    console.print(f"  Top5: {len(final.top5)}")
    console.print(f"  excluded: {len(final.excluded)}")
    console.print(f"  needs_manual_review: {len(final.needs_manual_review)}")
    console.print(f"  报告字符数: {len(md):,}")
    console.print(f"\n[green]✓ 最新副本:[/] {latest_path}")
    if archived_path is not None:
        console.print(f"[green]✓ 历史副本:[/] {archived_path}")


@app.command("review")
def review_cmd(
    pub_no: str = typer.Argument(..., help="专利公开号；要求三 Agent 已跑过"),
    out_dir: Optional[Path] = typer.Option(None, "--out"),
    reasoning: Optional[str] = typer.Option(None, "--reasoning", help="不传则用 .env 默认"),
    force: bool = typer.Option(
        False, "--force", help="强制重跑（默认 final_report.json 已存在则跳过）"
    ),
    verbose: int = typer.Option(1, "--verbose", "-v", count=True),
) -> None:
    """阶段 4：GPT-5.5 复核（合并去重 + 重打分） → final_report.json。"""
    pub_no = pub_no.strip().upper()
    log_file = _setup_logging(verbose, pub_no=pub_no, cmd="review")
    target_dir = out_dir or (config.INTERMEDIATE_DIR / pub_no)
    final_path = target_dir / "final_report.json"
    if final_path.exists() and not force:
        console.print(
            f"[yellow]✓ final_report.json 已存在，跳过[/]（用 --force 强制重跑）\n  {final_path}"
        )
        return
    if log_file:
        console.print(f"[dim]日志: {log_file}[/]")

    task_path = target_dir / "task_package.json"
    if not task_path.exists():
        console.print(f"[red]task_package.json 不存在: {task_path}[/]")
        raise typer.Exit(2)
    task = TaskPackage.model_validate_json(task_path.read_text(encoding="utf-8"))
    _log_cached_task_package(task, task_path)

    # 收集所有 agent_*.json
    agent_outputs: list[AgentOutput] = []
    for agent_name in ("deepseek", "kimi", "glm"):
        p = target_dir / f"agent_{agent_name}.json"
        if not p.exists():
            console.print(f"[yellow]skip 缺失:[/] {p.name}")
            continue
        agent_outputs.append(AgentOutput.model_validate_json(p.read_text(encoding="utf-8")))
    if not agent_outputs:
        console.print("[red]没有任何 agent_*.json，请先运行 find-competitors-all[/]")
        raise typer.Exit(2)

    console.rule(f"复核 · patent {pub_no}")
    n_total = sum(len(o.top5_candidates) for o in agent_outputs)
    console.print(
        f"已收集 {len(agent_outputs)} 份 agent 输出，候选合计 {n_total} 个"
        f"（GPT-5.5 将自行合并去重 + 复核）"
    )

    # 产出 candidate_pool.json，便于人工检查三 Agent 合并前后的证据归并关系。
    from .reviewer.merger import merge_agent_outputs
    candidate_pool = merge_agent_outputs(task, agent_outputs)
    pool_path = target_dir / "candidate_pool.json"
    pool_path.write_text(
        json.dumps(candidate_pool.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"已写入候选池快照: [green]{pool_path}[/]")

    # GPT-5.5 复核（合并去重 + 重打分 + 风险等级一并完成）
    eff = reasoning or config.REVIEWER_REASONING_EFFORT
    supplement_cache_path = target_dir / "review_supplement_cache.json"
    console.print(f"调用 GPT-5.5 复核（reasoning={eff}）...")
    console.print(f"复核补搜缓存: [dim]{supplement_cache_path}[/]")
    search_session = SearchSession(target_dir)
    final = review_agent_outputs(
        agent_outputs,
        task,
        reasoning_effort=eff,
        supplement_cache_path=supplement_cache_path,
        search_session=search_session,
    )

    final_path.write_text(
        json.dumps(final.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 展示
    console.rule(f"GPT-5.5 复核结果（耗时 {final.elapsed_seconds}s）")
    table = Table(show_lines=True)
    table.add_column("rank", style="cyan", justify="right")
    table.add_column("公司")
    table.add_column("产品")
    table.add_column("分数", justify="right")
    table.add_column("风险")
    for c in final.top5:
        table.add_row(
            str(c.rank), c.company, c.product[:40], f"{c.score:.1f}", c.risk_level,
        )
    console.print(table)
    console.print(
        f"\n[dim]excluded={len(final.excluded)}  needs_review={len(final.needs_manual_review)}[/]"
    )
    if final.notes:
        console.print(f"[dim]复核备注: {final.notes}[/]")
    console.print(f"\n[green]✓ 已写入:[/] {final_path}")


@app.command("find-competitors")
def find_competitors_cmd(
    pub_no: str = typer.Argument(..., help="专利公开号；要求 task_package.json 已存在"),
    agent: str = typer.Option("deepseek", "--agent", "-a", help="选择 agent: deepseek | kimi | glm"),
    out_dir: Optional[Path] = typer.Option(None, "--out", help="输出目录，默认 data/intermediate/<pub_no>"),
    verbose: int = typer.Option(1, "--verbose", "-v", count=True, help="日志级别：-v=INFO, -vv=DEBUG"),
) -> None:
    """阶段 2：调用单个 Agent 完成竞品发现 + 证据检索 + 特征匹配 + Top5。"""
    _setup_logging(verbose)
    pub_no = pub_no.strip().upper()
    target_dir = out_dir or (config.INTERMEDIATE_DIR / pub_no)
    task_path = target_dir / "task_package.json"
    if not task_path.exists():
        console.print(
            f"[red]task_package.json 不存在:[/] {task_path}\n"
            f"请先运行: [yellow]uv run patentradar decompose {pub_no}[/]"
        )
        raise typer.Exit(2)

    task = TaskPackage.model_validate_json(task_path.read_text(encoding="utf-8"))
    _log_cached_task_package(task, task_path)
    persp = get_perspective(agent)
    console.rule(f"Agent {persp.display_name}  ·  patent {pub_no}")
    console.print(
        f"  model: {persp.llm_endpoint.model}  perspective: {persp.perspective_label}\n"
        f"  专利: {task.patent.title}  权要 1 特征数: {len(task.claim_features)}\n"
        f"  主搜索源: {', '.join(persp.primary_engines)}"
    )

    search_session = SearchSession(target_dir)
    agent_obj = SearchAgent(persp, search_session=search_session)
    output = agent_obj.run(task)

    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"agent_{persp.name}.json"
    out_path.write_text(
        json.dumps(output.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    console.rule(f"Agent {persp.display_name} 输出概览")
    console.print(
        f"耗时: {output.elapsed_seconds}s · "
        f"queries: {len(output.queries_used)} · "
        f"top5: {len(output.top5_candidates)} · "
        f"discarded: {len(output.discarded_candidates)}"
    )

    table = Table(show_lines=True)
    table.add_column("rank", style="cyan", justify="right")
    table.add_column("公司")
    table.add_column("产品")
    table.add_column("分数", justify="right")
    table.add_column("匹配特征数", justify="right")
    for c in output.top5_candidates:
        n_match = sum(
            1 for fm in c.feature_match_table
            if fm.judgement in ("明确满足", "可能满足")
        )
        table.add_row(
            str(c.rank), c.company, c.product, f"{c.score:.1f}",
            f"{n_match}/{len(c.feature_match_table)}",
        )
    console.print(table)
    console.print(f"\n[green]✓ 已写入:[/] {out_path}")


def _print_features(pub_no: str, claim_1_text: str, features: list) -> None:
    console.rule(f"权利要求 1 拆解结果 - {pub_no}")
    console.print("[bold]最终版原文:[/]")
    console.print(claim_1_text, style="dim")
    table = Table(show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("技术特征原文")
    table.add_column("工程术语", style="magenta")
    table.add_column("必要", justify="center")
    for f in features:
        table.add_row(
            f.feature_id,
            f.feature_text,
            ", ".join(f.engineering_terms) or "—",
            "✓" if f.is_essential else "",
        )
    console.print(table)


@app.command("web")
def web_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址；要让局域网其它机器访问改 0.0.0.0"),
    port: int = typer.Option(8765, "--port", help="监听端口"),
    reload: bool = typer.Option(False, "--reload", help="开发模式：源码改动自动重载"),
) -> None:
    """启动 Web 仪表盘——实时展示四个 Agent 的运行日志。

    后端常驻独立进程，CLI 跑 ``find-competitors-all`` / ``review`` 时，
    Web 会通过 tail ``output/<pub>/runs/*.log`` 自动同步，不需要其他配置。
    """
    from .web.server import main as web_main
    console.print(f"[cyan]→ Web 仪表盘:[/] http://{host}:{port}")
    console.print(f"[dim]监听 output/ 下所有专利的 runs/*.log[/]")
    web_main(host=host, port=port, reload=reload)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/]")
        sys.exit(130)


if __name__ == "__main__":
    main()
