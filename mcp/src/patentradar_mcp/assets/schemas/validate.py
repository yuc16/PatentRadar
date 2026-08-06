"""Skill 内置的轻量 JSON Schema 校验器。

主 agent 在每个 subagent 跑完后调用这个脚本，把校验结果（成功 / 错误列表）
反馈给该 subagent，让它修正后重交。

用法：
    python skills/patentradar/schemas/validate.py <schema_name> <data_path>

schema_name 取值：task_package / top_competitor_report / full_claim_chart_report

成功：exit 0，stdout 打印 "OK <data_path>"
失败：exit 1，stdout 打印逐条错误（path + message）

依赖：jsonschema（pip install jsonschema 或项目 .venv 已装）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA_FILES = {
    "task_package": "task_package.schema.json",
    "top_competitor_report": "top_competitor_report.schema.json",
    "full_claim_chart_report": "full_claim_chart_report.schema.json",
}


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <schema_name> <data_path>", file=sys.stderr)
        print(f"schema_name ∈ {list(SCHEMA_FILES)}", file=sys.stderr)
        return 2

    schema_name = sys.argv[1]
    data_path = Path(sys.argv[2])

    if schema_name not in SCHEMA_FILES:
        print(f"unknown schema: {schema_name!r}; expected one of {list(SCHEMA_FILES)}", file=sys.stderr)
        return 2
    if not data_path.exists():
        print(f"data file not found: {data_path}", file=sys.stderr)
        return 2

    here = Path(__file__).resolve().parent
    schema_path = here / SCHEMA_FILES[schema_name]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = json.loads(data_path.read_text(encoding="utf-8"))

    try:
        from jsonschema import Draft7Validator
    except ImportError:
        print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
        return 2

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    business_errors: list[tuple[str, str]] = []
    if schema_name in {"top_competitor_report", "full_claim_chart_report"}:
        seen_companies: set[str] = set()
        for index, item in enumerate(data.get("top_competitors", [])):
            company = str(item.get("candidate", {}).get("company", "")).strip().lower()
            if company in seen_companies:
                business_errors.append(
                    (f"top_competitors.{index}.candidate.company", "TOP-N 中同公司只能保留最高分产品")
                )
            seen_companies.add(company)

    if not errors and not business_errors:
        print(f"OK {data_path}")
        return 0

    print(f"FAIL {data_path}: {len(errors) + len(business_errors)} error(s)")
    for err in errors:
        path = ".".join(str(p) for p in err.path) or "<root>"
        print(f"  [{path}] {err.message}")
    for path, message in business_errors:
        print(f"  [{path}] {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
