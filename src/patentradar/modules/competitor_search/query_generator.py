"""Step 1 wrapper for competitor query generation."""

from __future__ import annotations

from patentradar.core.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from patentradar.llm.workers.query_worker import generate_query_plan
from patentradar.schemas import QueryPlan, TaskPackage


def build_query_plan(
    task_package: TaskPackage,
    *,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> QueryPlan:
    return generate_query_plan(
        task_package=task_package,
        model=model,
        reasoning_effort=reasoning_effort,
    )
