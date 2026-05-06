from __future__ import annotations

import time
from collections import Counter
from typing import Any

from .config import LoadTestConfig
from .metrics import percentile_metrics, throughput_metrics
from .models import RequestResult


class MetricsSummaryBuilder:
    def __init__(self, config: LoadTestConfig):
        self.config = config

    def build(
        self,
        results: list[RequestResult],
        *,
        actual_input_tokens: int,
        started_at: float,
    ) -> dict[str, Any]:
        success = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        latencies = [r.latency_sec for r in success]
        wall_time = self.config.duration_sec
        if started_at and results:
            wall_time = max(0.001, time.time() - started_at)
        total_input_tokens = sum(r.input_tokens for r in success)
        total_output_tokens = sum(r.output_tokens for r in success)
        total_tokens = sum(r.total_tokens for r in success)
        ttfts = [r.ttft_sec for r in success if r.ttft_sec is not None]
        decode_times = [r.latency_sec - r.ttft_sec for r in success if r.ttft_sec is not None]
        error_counts = Counter(r.error_type or "UNKNOWN" for r in failed)
        status_counts = Counter(str(r.status) for r in results)

        return {
            "config": {
                "api_protocol": self.config.api_protocol,
                "anthropic_version": self.config.anthropic_version,
                "base_url": self.config.base_url,
                "endpoint": self.config.endpoint,
                "model": self.config.model,
                "concurrency": self.config.concurrency,
                "duration_sec": self.config.duration_sec,
                "input_tokens_target": self.config.input_tokens,
                "input_tokens_actual": actual_input_tokens,
                "max_output_tokens": self.config.max_output_tokens,
                "timeout_sec": self.config.timeout_sec,
                "warmup_requests": self.config.warmup_requests,
                "enable_stream": self.config.enable_stream,
            },
            "results": {
                "total_requests": len(results),
                "successful_requests": len(success),
                "failed_requests": len(failed),
                "success_rate": round(len(success) / len(results), 4) if results else 0.0,
                "qps": round(len(success) / wall_time, 4) if wall_time > 0 else 0.0,
                "rpm": round(len(success) * 60 / wall_time, 4) if wall_time > 0 else 0.0,
                **throughput_metrics(total_input_tokens, total_output_tokens, total_tokens, wall_time),
                **percentile_metrics(latencies, "latency_sec"),
                **percentile_metrics(ttfts, "ttft_sec"),
                "ttft_samples": len(ttfts),
                **percentile_metrics(decode_times, "decode_sec"),
                "status_counts": dict(status_counts),
                "error_counts": dict(error_counts),
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
            },
        }


class MetricsAccumulator:
    def __init__(self) -> None:
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0
        self.latencies: list[float] = []
        self.ttfts: list[float] = []
        self.decode_times: list[float] = []
        self.error_counts: Counter[str] = Counter()
        self.status_counts: Counter[str] = Counter()

    def record(self, result: RequestResult) -> None:
        self.total_requests += 1
        self.status_counts[str(result.status)] += 1
        if result.ok:
            self.successful_requests += 1
            self.total_input_tokens += result.input_tokens
            self.total_output_tokens += result.output_tokens
            self.total_tokens += result.total_tokens
            self.latencies.append(result.latency_sec)
            if result.ttft_sec is not None:
                self.ttfts.append(result.ttft_sec)
                self.decode_times.append(result.latency_sec - result.ttft_sec)
        else:
            self.failed_requests += 1
            self.error_counts[result.error_type or "UNKNOWN"] += 1

    def reset(self) -> None:
        self.__init__()

    def build_summary(
        self,
        config: LoadTestConfig,
        *,
        actual_input_tokens: int,
        started_at: float,
    ) -> dict[str, Any]:
        wall_time = config.duration_sec
        if started_at and self.total_requests:
            wall_time = max(0.001, time.time() - started_at)

        return {
            "config": {
                "api_protocol": config.api_protocol,
                "anthropic_version": config.anthropic_version,
                "base_url": config.base_url,
                "endpoint": config.endpoint,
                "model": config.model,
                "concurrency": config.concurrency,
                "duration_sec": config.duration_sec,
                "input_tokens_target": config.input_tokens,
                "input_tokens_actual": actual_input_tokens,
                "max_output_tokens": config.max_output_tokens,
                "timeout_sec": config.timeout_sec,
                "warmup_requests": config.warmup_requests,
                "enable_stream": config.enable_stream,
            },
            "results": {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate": round(self.successful_requests / self.total_requests, 4) if self.total_requests else 0.0,
                "qps": round(self.successful_requests / wall_time, 4) if wall_time > 0 else 0.0,
                "rpm": round(self.successful_requests * 60 / wall_time, 4) if wall_time > 0 else 0.0,
                **throughput_metrics(self.total_input_tokens, self.total_output_tokens, self.total_tokens, wall_time),
                **percentile_metrics(self.latencies, "latency_sec"),
                **percentile_metrics(self.ttfts, "ttft_sec"),
                "ttft_samples": len(self.ttfts),
                **percentile_metrics(self.decode_times, "decode_sec"),
                "status_counts": dict(self.status_counts),
                "error_counts": dict(self.error_counts),
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_tokens,
            },
        }
