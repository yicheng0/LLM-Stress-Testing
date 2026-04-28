from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glm_tpm_test import RequestResult, _aggregate_by_time_window, _calculate_histogram


def load_details(path: str | None, *, page: int = 1, page_size: int = 100) -> tuple[int, list[dict[str, Any]]]:
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


def build_chart_data(summary: dict[str, Any] | None, details_path: str | None) -> dict[str, Any]:
    if summary and summary.get("matrix"):
        return build_matrix_chart_data(summary.get("results_matrix") or [])

    details = load_request_results(details_path)
    success = [item for item in details if item.ok]
    failed = [item for item in details if not item.ok]

    latencies = [item.latency_sec for item in success]
    ttfts = [item.ttft_sec for item in success if item.ttft_sec is not None]
    decode_times = [
        item.latency_sec - item.ttft_sec
        for item in success
        if item.ttft_sec is not None
    ]

    timeseries = _aggregate_by_time_window(details, window_sec=2.0)
    first_ts = min((item.started_at for item in success), default=0.0)
    normalized_timeseries = [
        {
            "time_sec": round(bucket["timestamp"] - first_ts, 2),
            "qps": round(bucket["qps"], 4),
            "tpm": round(bucket["tpm"], 2),
            "avg_ttft": round(bucket["avg_ttft"], 4) if bucket["avg_ttft"] is not None else None,
        }
        for bucket in timeseries
    ]

    error_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for item in details:
        status_counts[str(item.status)] = status_counts.get(str(item.status), 0) + 1
        if not item.ok:
            key = item.error_type or "UNKNOWN"
            error_counts[key] = error_counts.get(key, 0) + 1

    return {
        "latency_histogram": _calculate_histogram(latencies, bins=30),
        "ttft_histogram": _calculate_histogram(ttfts, bins=30),
        "decode_histogram": _calculate_histogram(decode_times, bins=30),
        "timeseries": normalized_timeseries,
        "error_counts": error_counts,
        "status_counts": status_counts,
        "detail_count": len(details),
        "success_count": len(success),
        "failed_count": len(failed),
    }


def build_matrix_chart_data(results_matrix: list[dict[str, Any]]) -> dict[str, Any]:
    points = []
    for item in results_matrix:
        cfg = item.get("matrix_config") or item.get("config") or {}
        res = item.get("results") or {}
        points.append({
            "input_tokens": cfg.get("input_tokens") or item.get("config", {}).get("input_tokens_target"),
            "concurrency": cfg.get("concurrency") or item.get("config", {}).get("concurrency"),
            "rpm": res.get("rpm"),
            "qps": res.get("qps"),
            "total_tpm": res.get("total_tpm"),
            "success_rate": res.get("success_rate"),
            "latency_p95": res.get("latency_sec_p95"),
            "ttft_p95": res.get("ttft_sec_p95"),
        })

    return {
        "matrix_points": points,
        "detail_count": 0,
        "success_count": 0,
        "failed_count": 0,
    }
