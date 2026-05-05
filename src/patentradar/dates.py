"""Date parsing helpers used by patent and candidate hard checks."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date


_YMD_RE = re.compile(r"(?P<y>19\d{2}|20\d{2})[-/.年](?P<m>\d{1,2})(?:[-/.月](?P<d>\d{1,2})日?)?")
_YEAR_RE = re.compile(r"\b(?P<y>19\d{2}|20\d{2})\b")


@dataclass(frozen=True)
class DateRange:
    original: str
    normalized: str
    start: date
    end: date


def normalize_date_string(value: str | None) -> str | None:
    """Return YYYY-MM-DD / YYYY-MM / YYYY if the text contains a recognizable date."""
    rng = parse_date_range(value)
    return rng.normalized if rng else None


def parse_date_range(value: str | None) -> DateRange | None:
    text = (value or "").strip()
    if not text:
        return None
    m = _YMD_RE.search(text)
    if m:
        y = int(m.group("y"))
        mo = int(m.group("m"))
        if not 1 <= mo <= 12:
            return None
        d_text = m.group("d")
        if d_text:
            d = int(d_text)
            if not 1 <= d <= calendar.monthrange(y, mo)[1]:
                return None
            dt = date(y, mo, d)
            return DateRange(text, dt.isoformat(), dt, dt)
        start = date(y, mo, 1)
        end = date(y, mo, calendar.monthrange(y, mo)[1])
        return DateRange(text, f"{y:04d}-{mo:02d}", start, end)

    m = _YEAR_RE.search(text)
    if m:
        y = int(m.group("y"))
        return DateRange(text, f"{y:04d}", date(y, 1, 1), date(y, 12, 31))
    return None


def is_after_application(launch_date: str | None, application_date: str | None) -> bool | None:
    """Return whether a product launch date is strictly after patent application date.

    Partial launch dates are treated conservatively:
    - return True only when the earliest possible launch date is after application;
    - return False only when the latest possible launch date is on/before application;
    - otherwise return None so the candidate is not excluded automatically.
    """
    launch = parse_date_range(launch_date)
    application = parse_date_range(application_date)
    if not launch or not application:
        return None
    app_day = application.start
    if launch.start > app_day:
        return True
    if launch.end <= app_day:
        return False
    return None
