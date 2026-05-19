from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loadtest import RequestResult, build_matrix_chart_data, build_single_chart_data


def load_details(
    path: str | None,
    *,
    page: int = 1,
    page_size: int = 100,
    total_count: int | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    if not path or not Path(path).exists():
        return 0, []

    page = max(1, page)
    page_size = min(max(1, page_size), 500)
    start = (page - 1) * page_size
    end = start + page_size

    total = 0
    items: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if start <= total < end:
                items.append(json.loads(line))
            total += 1
            if total_count is not None and total >= end:
                return total_count, items
    return total, items


def load_request_results(path: str | None) -> list[RequestResult]:
    if not path or not Path(path).exists():
        return []

    results: list[RequestResult] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            results.append(RequestResult(**data))
    return results


def load_chart_cache(path: str | None) -> dict[str, Any] | None:
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_chart_data(
    summary: dict[str, Any] | None,
    details_path: str | None,
    *,
    charts_path: str | None = None,
) -> dict[str, Any]:
    cached = load_chart_cache(charts_path)
    if cached is not None:
        return cached
    if summary and summary.get("matrix"):
        return build_matrix_chart_data(summary.get("results_matrix") or [])
    return build_single_chart_data(load_request_results(details_path))
