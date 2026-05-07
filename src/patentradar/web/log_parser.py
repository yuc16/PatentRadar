"""把 patentradar 日志解析成前端事件流。

日志文件由 [`cli._setup_logging`](../cli.py) 写入：每行带 ISO 时间戳的是真实结构化日志，
另有不带时间戳的 stdout 镜像行（开头空格或形如 ``19:21:17 ...``），是 RichHandler
的样式重复，**直接忽略**。

每行解析为一个 ``LogEvent``：
- ``t`` 相对秒（首行为 0）
- ``agent`` ∈ {controller, deepseek, kimi, glm}
- ``kind`` ∈ {info, hit, drop, emit, warn} —— 仅控制颜色
- ``text`` 实际可读消息
- ``url`` 第一个出现的网址（若有）
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator


# 真实结构化日志行：``2026-05-07 19:21:17,107 patentradar.agent INFO | <message>``
_REAL_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(?P<ms>\d{3})\s+"
    r"(?P<logger>\S+)\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\|\s*"
    r"(?P<msg>.*)$"
)
_AGENT_TAG_RE = re.compile(r"\[(?P<a>deepseek|kimi|glm|reviewer|controller)\]")
_URL_KW_RE = re.compile(r"url=(?P<u>https?://\S+)")
_URL_PLAIN_RE = re.compile(r"(?<![\w.])(?P<u>https?://[\w.\-]+(?:/[^\s)\]\"'>]*)?)")


@dataclass(frozen=True)
class LogEvent:
    t: float
    agent: str
    kind: str
    text: str
    url: str | None
    raw_ts: str  # "HH:MM:SS"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- 行级解析 ----------


def _classify_kind(msg: str) -> str:
    """根据消息体推断颜色档位。"""
    upper = f" {msg} "
    if " EMIT " in upper or upper.lstrip().startswith("EMIT "):
        return "emit"
    if " DROP " in upper or " 丢弃 " in upper:
        return "drop"
    if " WARN " in upper or "WARNING" in upper:
        return "warn"
    if " HIT " in upper or " HIT\t" in upper or "search HIT" in msg:
        return "hit"
    return "info"


def _classify_agent(logger: str, msg: str) -> str:
    """优先看消息体内的 ``[agent]`` 标签，否则按 logger 归到 controller。"""
    m = _AGENT_TAG_RE.search(msg)
    if m:
        a = m.group("a")
        if a in {"deepseek", "kimi", "glm"}:
            return a
        # [reviewer] / [controller] 都算控制器
        return "controller"
    if logger.endswith(("controller", "reviewer", "fetch", "patent", "compactor")):
        return "controller"
    if logger.startswith("patentradar.reviewer") or "reviewer" in logger:
        return "controller"
    if logger.startswith("patentradar.fetch") or "patentradar.compactor" in logger:
        return "controller"
    # 默认归到 controller，避免无主行
    return "controller"


def _extract_url(msg: str) -> str | None:
    m = _URL_KW_RE.search(msg)
    if m:
        return m.group("u").rstrip(",;)")
    m = _URL_PLAIN_RE.search(msg)
    if m:
        return m.group("u").rstrip(",;)")
    return None


def parse_line(line: str, *, t_base: float | None) -> tuple[LogEvent | None, float | None]:
    """解析单行；返回 (事件, 新的 t_base)。

    若该行不是结构化真实日志，返回 (None, t_base 不变)。
    """
    m = _REAL_LINE_RE.match(line.rstrip("\n"))
    if not m:
        return None, t_base
    ts_str = m.group("ts")
    ms = int(m.group("ms"))
    logger = m.group("logger")
    msg = m.group("msg")
    dt = datetime.fromisoformat(ts_str.replace(" ", "T"))
    epoch = dt.timestamp() + ms / 1000.0
    if t_base is None:
        t_base = epoch
    t = epoch - t_base
    raw_ts = dt.strftime("%H:%M:%S")
    agent = _classify_agent(logger, msg)
    kind = _classify_kind(msg)
    url = _extract_url(msg)
    # 文本：保留 logger 前缀让用户能识别来源
    short_logger = logger.split(".", 1)[-1] if "." in logger else logger
    text = f"{raw_ts} {short_logger} | {msg}"
    return LogEvent(t=round(t, 3), agent=agent, kind=kind, text=text, url=url, raw_ts=raw_ts), t_base


def iter_events(
    paths: Iterable[Path],
    *,
    start_offset: int = 0,
) -> Iterator[LogEvent]:
    """按 ``paths`` 顺序串联解析多个 log 文件，统一对齐 t_base。

    ``start_offset`` 仅对**最后一个文件**生效，用于增量 tail。
    """
    paths = list(paths)
    t_base: float | None = None
    for i, p in enumerate(paths):
        if not p.exists():
            continue
        is_last = i == len(paths) - 1
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            if is_last and start_offset:
                fh.seek(start_offset)
            for line in fh:
                ev, t_base = parse_line(line, t_base=t_base)
                if ev is not None:
                    yield ev


# ---------- patent 目录扫描 ----------


def list_patent_runs(output_root: Path) -> list[dict]:
    """扫描 ``output_root`` 下所有 patent 的 runs/*.log，返回前端可显示的概要。

    每个专利返回：
    ``{pub_no, title?, last_run_at, log_paths, has_active_run}``
    """
    out: list[dict] = []
    if not output_root.exists():
        return out
    for pub_dir in sorted(output_root.iterdir()):
        if not pub_dir.is_dir():
            continue
        runs_dir = pub_dir / "runs"
        if not runs_dir.exists():
            continue
        logs = sorted(runs_dir.glob("*.log"))
        if not logs:
            continue
        last = logs[-1]
        last_mtime = last.stat().st_mtime
        # 阈值要覆盖单次 LLM 调用的最大无日志间隔（~3min），否则会误判为已结束
        active = (datetime.now().timestamp() - last_mtime) < 300
        out.append({
            "pub_no": pub_dir.name,
            "log_paths": [str(p.relative_to(output_root.parent)) for p in logs],
            "last_run_at": datetime.fromtimestamp(last_mtime).isoformat(timespec="seconds"),
            "has_active_run": active,
        })
    # 最近活跃的排前
    out.sort(key=lambda x: x["last_run_at"], reverse=True)
    return out


def find_competitors_log(pub_dir: Path) -> Path | None:
    """返回最新一次 find-competitors-all 的 log（或退而求其次的最新 log）。

    布局演化：
    - **当前**：``runs/<YYYYMMDD_HHMMSS>/<cmd>.log``（一次工作流一个目录，4 份 log 平铺）
    - 旧版 1：``runs/<YYYYMMDD>/<HHMMSS>_<cmd>/run.log``
    - 旧版 2：``runs/<YYYYMMDD>/<HHMMSS>_<cmd>.log``
    - 旧版 3：``runs/<TS>_<cmd>.log``

    优先级：先按文件名 / 父目录名匹配 ``find-competitors-all``，找不到再退到 review / 任意 log。
    """
    runs = pub_dir / "runs"
    if not runs.exists():
        return None

    def _matches(p: Path, filt: str) -> bool:
        if not filt:
            return True
        # 新布局：runs/<RUN>/<cmd>.log
        # 旧布局 1：runs/<date>/<HHMMSS>_<cmd>/run.log → 看父目录名
        return filt in p.name or filt in p.parent.name

    def _scan(filt: str) -> list[Path]:
        return [p for p in runs.rglob("*.log") if _matches(p, filt)]

    for filt in ("find-competitors-all", "find-competitors", "review", ""):
        cands = _scan(filt)
        if cands:
            cands.sort(key=lambda p: p.stat().st_mtime)
            return cands[-1]
    return None


def get_current_run(output_root: Path) -> dict | None:
    """返回**最新一次** find-competitors run 的元信息（跨所有专利）。

    "当前 run" = 所有专利下最新建的 log 文件。前端只展示这一次。

    返回 None 表示项目里没有任何 run（用户还没跑过 / 没产生 log）。
    """
    if not output_root.exists():
        return None
    latest_log: Path | None = None
    latest_pub: str | None = None
    for pub_dir in output_root.iterdir():
        if not pub_dir.is_dir():
            continue
        log = find_competitors_log(pub_dir)
        if not log:
            continue
        if latest_log is None or log.stat().st_ctime > latest_log.stat().st_ctime:
            latest_log = log
            latest_pub = pub_dir.name
    if latest_log is None:
        return None
    st = latest_log.stat()
    return {
        "pub_no": latest_pub,
        "log_path": str(latest_log.relative_to(output_root.parent)),
        "started_at": st.st_ctime,
        "last_mtime": st.st_mtime,
        "size": st.st_size,
        "is_active": (datetime.now().timestamp() - st.st_mtime) < 300,
    }
