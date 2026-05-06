from __future__ import annotations

import statistics
import math
from typing import Any, Dict, List, Optional

from .models import RequestResult


def _aggregate_by_time_window(details: List[RequestResult], window_sec: float = 1.0) -> List[Dict[str, Any]]:
    if not details:
        return []

    success_details = [d for d in details if d.ok]
    if not success_details:
        return []

    buckets: list[dict[str, Any]] = []
    start_time = min(d.started_at for d in success_details)
    end_time = max(d.ended_at for d in success_details)
    current = start_time
    idx = 0
    ordered = sorted(success_details, key=lambda item: item.started_at)

    while current < end_time:
        bucket_end = current + window_sec
        window_requests: list[RequestResult] = []
        while idx < len(ordered) and ordered[idx].started_at < bucket_end:
            if ordered[idx].started_at >= current:
                window_requests.append(ordered[idx])
            idx += 1
        if window_requests:
            total_tokens = sum(d.total_tokens for d in window_requests)
            ttfts = [d.ttft_sec for d in window_requests if d.ttft_sec is not None]
            buckets.append({
                "timestamp": current,
                "qps": len(window_requests) / window_sec,
                "tpm": total_tokens / window_sec * 60,
                "avg_ttft": statistics.mean(ttfts) if ttfts else None,
            })
        current = bucket_end
    return buckets


def _calculate_histogram(values: List[float], bins: int = 50) -> Dict[str, List]:
    if not values:
        return {"bins": [], "counts": []}
    min_val, max_val = min(values), max(values)
    if min_val == max_val:
        return {"bins": [min_val], "counts": [len(values)]}
    bin_width = (max_val - min_val) / bins
    bin_edges = [min_val + i * bin_width for i in range(bins + 1)]
    counts = [0] * bins
    for val in values:
        bin_idx = min(int((val - min_val) / bin_width), bins - 1)
        counts[bin_idx] += 1
    bin_centers = [(bin_edges[i] + bin_edges[i + 1]) / 2 for i in range(bins)]
    return {"bins": bin_centers, "counts": counts}


def _analyze_metric(
    value: Optional[float],
    thresholds: List[tuple[float, str]],
) -> Optional[str]:
    if value is None:
        return None
    for threshold, message in thresholds:
        if value > threshold:
            return message
    return thresholds[-1][1] if thresholds else None


def percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    k = (len(values) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def percentile_metrics(values: List[float], prefix: str) -> dict:
    if not values:
        return {
            f"{prefix}_avg": None,
            f"{prefix}_p50": None,
            f"{prefix}_p90": None,
            f"{prefix}_p95": None,
            f"{prefix}_p99": None,
        }
    return {
        f"{prefix}_avg": round(statistics.mean(values), 4),
        f"{prefix}_p50": round(percentile(values, 0.50), 4),
        f"{prefix}_p90": round(percentile(values, 0.90), 4),
        f"{prefix}_p95": round(percentile(values, 0.95), 4),
        f"{prefix}_p99": round(percentile(values, 0.99), 4),
    }


def throughput_metrics(input_tokens: int, output_tokens: int, total_tokens: int, wall_time: float) -> dict:
    if wall_time <= 0:
        return {
            "input_tpm": 0.0, "output_tpm": 0.0, "total_tpm": 0.0,
            "input_tps": 0.0, "output_tps": 0.0, "total_tps": 0.0,
        }
    return {
        "input_tpm": round(input_tokens * 60 / wall_time, 2),
        "output_tpm": round(output_tokens * 60 / wall_time, 2),
        "total_tpm": round(total_tokens * 60 / wall_time, 2),
        "input_tps": round(input_tokens / wall_time, 2),
        "output_tps": round(output_tokens / wall_time, 2),
        "total_tps": round(total_tokens / wall_time, 2),
    }
