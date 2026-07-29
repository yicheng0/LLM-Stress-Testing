from __future__ import annotations

import copy
import functools
import json
import math
from pathlib import Path
from typing import Any

from loadtest import RequestResult, build_matrix_chart_data, build_single_chart_data
from loadtest.metrics import percentile_metrics


_LATENCY_PERCENTILE_FIELDS = ("avg", "p50", "p90", "p95", "p99")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@functools.lru_cache(maxsize=128)
def _load_stream_latency_metrics(path: str, modified_ns: int, size: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    del modified_ns, size  # File metadata is part of the cache key.
    ttfts: list[float] = []
    decode_times: list[float] = []
    try:
        with Path(path).open("r", encoding="utf-8") as detail_file:
            for line in detail_file:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(item, dict) or item.get("ok") is not True:
                    continue
                latency = _finite_number(item.get("latency_sec"))
                ttft = _finite_number(item.get("ttft_sec"))
                if latency is None or ttft is None or latency < 0 or ttft < 0 or ttft > latency:
                    continue
                ttfts.append(ttft)
                decode_times.append(latency - ttft)
    except OSError:
        return (), ()
    return tuple(ttfts), tuple(decode_times)


def backfill_stream_latency_metrics(
    summary: dict[str, Any] | None,
    details_path: str | None,
    *,
    enable_stream: bool | None = None,
) -> dict[str, Any] | None:
    """Restore missing TTFT/Decode percentiles from persisted request details."""
    if not summary or summary.get("matrix"):
        return summary

    stream_enabled = enable_stream
    if stream_enabled is None:
        stream_enabled = bool((summary.get("config") or {}).get("enable_stream"))
    if not stream_enabled or not details_path or not Path(details_path).exists():
        return summary

    results = summary.get("results")
    if not isinstance(results, dict):
        return summary

    metric_keys = [
        f"{prefix}_{field}"
        for prefix in ("ttft_sec", "decode_sec")
        for field in _LATENCY_PERCENTILE_FIELDS
    ]
    if all(results.get(key) is not None for key in metric_keys) and results.get("ttft_samples") is not None:
        return summary

    try:
        stat = Path(details_path).stat()
        ttfts, decode_times = _load_stream_latency_metrics(details_path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return summary

    if not ttfts:
        return summary

    enriched = copy.deepcopy(summary)
    enriched_results = enriched["results"]
    calculated = {
        **percentile_metrics(ttfts, "ttft_sec"),
        **percentile_metrics(decode_times, "decode_sec"),
    }
    for key, value in calculated.items():
        if enriched_results.get(key) is None:
            enriched_results[key] = value
    if not enriched_results.get("ttft_samples"):
        enriched_results["ttft_samples"] = len(ttfts)
    return enriched


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
