"""Project-wide constants and environment-backed settings."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("PATENTRADAR_MODEL", "gpt-5.5")
DEFAULT_CONTEXT_LENGTH = int(os.getenv("PATENTRADAR_CONTEXT_LENGTH", "258000"))
DEFAULT_REASONING_EFFORT = os.getenv("PATENTRADAR_REASONING_EFFORT", "high")
GOOGLE_PATENTS_BASE = "https://patents.google.com/patent"

TECHNOLOGY_TAGS = [
    "动力电池",
    "电驱系统",
    "充配电系统",
    "整车与车身底盘",
    "智能驾驶",
    "智能座舱与车联网",
    "制造工艺与装备",
    "材料与化学",
    "其他",
]
