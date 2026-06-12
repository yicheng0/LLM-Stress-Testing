from __future__ import annotations

import statistics
from typing import Any

from .metrics import _aggregate_by_time_window, _calculate_histogram
from .models import RequestResult


def build_single_chart_data(details: list[RequestResult], *, window_sec: float = 2.0, bins: int = 30) -> dict[str, Any]:
    success = [item for item in details if item.ok]
    failed = [item for item in details if not item.ok]

    latencies = [item.latency_sec for item in success]
    ttfts = [item.ttft_sec for item in success if item.ttft_sec is not None]
    decode_times = [
        item.latency_sec - item.ttft_sec
        for item in success
        if item.ttft_sec is not None
    ]

    timeseries = _aggregate_by_time_window(details, window_sec=window_sec)
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
        "latency_histogram": _calculate_histogram(latencies, bins=bins),
        "ttft_histogram": _calculate_histogram(ttfts, bins=bins),
        "decode_histogram": _calculate_histogram(decode_times, bins=bins),
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
            "total_tps": res.get("total_tps"),
            "cache_inclusive_tpm": res.get("cache_inclusive_tpm"),
            "cache_hit_tpm": res.get("cache_hit_tpm"),
            "cache_hit_rate": res.get("cache_hit_rate"),
            "total_cached_input_tokens": res.get("total_cached_input_tokens"),
            "total_cache_creation_input_tokens": res.get("total_cache_creation_input_tokens"),
            "total_cache_inclusive_tokens": res.get("total_cache_inclusive_tokens"),
            "success_rate": res.get("success_rate"),
            "latency_avg": res.get("latency_sec_avg"),
            "latency_p50": res.get("latency_sec_p50"),
            "latency_p95": res.get("latency_sec_p95"),
            "latency_p99": res.get("latency_sec_p99"),
            "ttft_avg": res.get("ttft_sec_avg"),
            "ttft_p50": res.get("ttft_sec_p50"),
            "ttft_p95": res.get("ttft_sec_p95"),
            "ttft_p99": res.get("ttft_sec_p99"),
        })

    return {
        "matrix_points": points,
        "detail_count": 0,
        "success_count": 0,
        "failed_count": 0,
    }


class ChartDataAccumulator:
    def __init__(self, *, window_sec: float = 2.0, bins: int = 30) -> None:
        self.window_sec = window_sec
        self.bins = bins
        self.detail_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.latencies: list[float] = []
        self.ttfts: list[float] = []
        self.decode_times: list[float] = []
        self.error_counts: dict[str, int] = {}
        self.status_counts: dict[str, int] = {}
        self._first_success_ts: float | None = None
        self._window_start: float | None = None
        self._windows: dict[int, dict[str, Any]] = {}

    def record(self, item: RequestResult) -> None:
        self.detail_count += 1
        self.status_counts[str(item.status)] = self.status_counts.get(str(item.status), 0) + 1
        if not item.ok:
            self.failed_count += 1
            key = item.error_type or "UNKNOWN"
            self.error_counts[key] = self.error_counts.get(key, 0) + 1
            return

        self.success_count += 1
        self.latencies.append(item.latency_sec)
        if item.ttft_sec is not None:
            self.ttfts.append(item.ttft_sec)
            self.decode_times.append(item.latency_sec - item.ttft_sec)
        if self._first_success_ts is None:
            self._first_success_ts = item.started_at
            self._window_start = item.started_at
        assert self._window_start is not None
        index = int((item.started_at - self._window_start) // self.window_sec)
        bucket = self._windows.setdefault(
            index,
            {
                "timestamp": self._window_start + index * self.window_sec,
                "requests": 0,
                "total_tokens": 0,
                "ttfts": [],
            },
        )
        bucket["requests"] += 1
        bucket["total_tokens"] += item.total_tokens
        if item.ttft_sec is not None:
            bucket["ttfts"].append(item.ttft_sec)

    def build(self) -> dict[str, Any]:
        first_ts = self._first_success_ts or 0.0
        timeseries = []
        for bucket in sorted(self._windows.values(), key=lambda item: item["timestamp"]):
            ttfts = bucket["ttfts"]
            timeseries.append({
                "time_sec": round(bucket["timestamp"] - first_ts, 2),
                "qps": round(bucket["requests"] / self.window_sec, 4),
                "tpm": round(bucket["total_tokens"] / self.window_sec * 60, 2),
                "avg_ttft": round(statistics.mean(ttfts), 4) if ttfts else None,
            })
        return {
            "latency_histogram": _calculate_histogram(self.latencies, bins=self.bins),
            "ttft_histogram": _calculate_histogram(self.ttfts, bins=self.bins),
            "decode_histogram": _calculate_histogram(self.decode_times, bins=self.bins),
            "timeseries": timeseries,
            "error_counts": self.error_counts,
            "status_counts": self.status_counts,
            "detail_count": self.detail_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
        }
