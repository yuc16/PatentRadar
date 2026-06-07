"""竞品上市日期 vs 专利申请日的比较——失格判定专用。

launch_date 是 LLM 给的自由文本中文（如「2022年Q3量产」「不晚于2019年2月」），
不可靠；application_date 通常是 Google Patents 的 ISO `yyyy-mm-dd`。失格（早于申请日
→ 淘汰候选）是会**移除潜在侵权方**的高风险决定，所以一律保守：只有能可靠判定
launch 确实更早时才返回 True，任何不确定都返回 False（保留候选）。
"""

from __future__ import annotations

import re

_YEAR = r"(?:19|20)\d{2}"


def _app_year_month(application_date: str) -> tuple[int, int | None] | None:
    """专利申请日 → (year, month|None)。无法解析年份返回 None。"""
    m = re.search(rf"({_YEAR})[-/.年]\s*(\d{{1,2}})", application_date or "")
    if m:
        month = int(m.group(2))
        return int(m.group(1)), (month if 1 <= month <= 12 else None)
    m = re.search(_YEAR, application_date or "")
    return (int(m.group()), None) if m else None


def _launch_month_for_year(launch_date: str, year: int) -> int | None:
    """在自由文本里找紧挨 `year` 的月份信号：`2020年3月` / `2020-03` / `2020/03` /
    `2020年Q3`（季度→起始月）。找不到返回 None。"""
    m = re.search(rf"{year}\s*[-/.年]\s*(\d{{1,2}})\s*月?", launch_date)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return month
    m = re.search(rf"{year}\s*年?\s*[QqＱ]\s*([1-4])", launch_date)
    if m:
        return (int(m.group(1)) - 1) * 3 + 1
    return None


def launch_before_application(launch_date: str, application_date: str) -> bool:
    """launch 是否**可靠地**早于专利申请日。保守：不确定一律 False。

    规则：
      - 申请日无法解析年份 → False。
      - launch 文本里出现 0 个或 ≥2 个不同年份 → 含糊（可能混了多个 SKU）→ False。
      - launch 年 < 申请年 → True；launch 年 > 申请年 → False。
      - 同年：仅当两边月份都可知且 launch 月 < 申请月才 True，否则 False。
    """
    app = _app_year_month(application_date)
    if app is None:
        return False
    app_year, app_month = app

    years = sorted({int(y) for y in re.findall(_YEAR, launch_date or "")})
    if len(years) != 1:
        return False
    launch_year = years[0]

    if launch_year < app_year:
        return True
    if launch_year > app_year:
        return False

    launch_month = _launch_month_for_year(launch_date, launch_year)
    if launch_month is None or app_month is None:
        return False
    return launch_month < app_month
