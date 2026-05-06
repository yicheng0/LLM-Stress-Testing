from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Awaitable, Callable

from loadtest import LoadTestRunner
from loadtest.config import LoadTestConfig
from loadtest.result_writer import ReportArtifactWriter

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
LogCallback = Callable[[str, str], Awaitable[None] | None]


class WebLoadTestRunner:
    def __init__(
        self,
        task_id: str,
        config: dict[str, Any],
        results_dir: Path,
        *,
        progress_callback: ProgressCallback | None = None,
        stop_event=None,
        log_callback: LogCallback | None = None,
    ) -> None:
        self.task_id = task_id
        self.config = config
        self.results_dir = results_dir
        self.progress_callback = progress_callback
        self.stop_event = stop_event
        self.log_callback = log_callback

    def to_namespace(self) -> argparse.Namespace:
        config = LoadTestConfig.from_mapping({
            "api_protocol": self.config.get("api_protocol", "openai"),
            "anthropic_version": self.config.get("anthropic_version", "2023-06-01"),
            "base_url": self.config["base_url"],
            "api_key": self.config["api_key"],
            "model": self.config["model"],
            "endpoint": self.config.get("endpoint", "/v1/chat/completions"),
            "concurrency": int(self.config.get("concurrency", 10)),
            "duration_sec": int(self.config.get("duration_sec", 60)),
            "input_tokens": int(self.config.get("input_tokens", 1000)),
            "max_output_tokens": int(self.config.get("max_output_tokens", 128)),
            "temperature": float(self.config.get("temperature", 0.0)),
            "timeout_sec": int(self.config.get("timeout_sec", 600)),
            "connect_timeout_sec": int(self.config.get("connect_timeout_sec", 30)),
            "warmup_requests": int(self.config.get("warmup_requests", 0)),
            "max_retries": int(self.config.get("max_retries", 2)),
            "retry_backoff_base": float(self.config.get("retry_backoff_base", 1.0)),
            "retry_backoff_max": float(self.config.get("retry_backoff_max", 8.0)),
            "think_time_ms": int(self.config.get("think_time_ms", 0)),
            "output_dir": str(self.results_dir),
            "enable_stream": bool(self.config.get("enable_stream", True)),
            "matrix_mode": bool(self.config.get("matrix_mode", False)),
            "input_tokens_list": self.config.get("input_tokens_list", ""),
            "concurrency_list": self.config.get("concurrency_list", ""),
            "matrix_duration_sec": int(self.config.get("matrix_duration_sec", 60)),
        })
        return config.to_namespace()

    async def run(self) -> dict[str, Any]:
        task_dir = self.results_dir / self.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        args = self.to_namespace()
        args.output_dir = str(task_dir)
        config = LoadTestConfig.from_namespace(args)
        writer = ReportArtifactWriter(task_dir)

        tester = LoadTestRunner(
            config,
            progress_callback=self.progress_callback,
            stop_event=self.stop_event,
            log_callback=self.log_callback,
        )

        if config.matrix_mode:
            results_matrix = await tester.run_matrix()
            summary = {
                "config": config.safe_dict(),
                "matrix": True,
                "test_points": len(results_matrix),
                "results_matrix": results_matrix,
            }
            files = writer.write_matrix(results_matrix, summary)

            return {
                "summary": summary,
                "files": files,
            }

        summary = await tester.run()
        files = writer.write_single(summary, tester.results)

        return {
            "summary": summary,
            "files": files,
        }
