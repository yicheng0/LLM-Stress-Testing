from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from glm_tpm_test import (
    LoadTester,
    generate_matrix_csv,
    render_html_report,
    render_markdown_report,
    render_matrix_report,
)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
LogCallback = Callable[[str, str], Awaitable[None] | None]


class WebTestRunner:
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
        data = {
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
        }
        return argparse.Namespace(**data)

    async def run(self) -> dict[str, Any]:
        task_dir = self.results_dir / self.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        args = self.to_namespace()
        args.output_dir = str(task_dir)

        tester = LoadTester(
            args,
            progress_callback=self.progress_callback,
            stop_event=self.stop_event,
            log_callback=self.log_callback,
        )
        ts = time.strftime("%Y%m%d_%H%M%S")

        if args.matrix_mode:
            results_matrix = await tester.run_matrix()
            summary = {
                "config": self._safe_config(args),
                "matrix": True,
                "test_points": len(results_matrix),
                "results_matrix": results_matrix,
            }
            summary_path = task_dir / f"matrix_summary_{ts}.json"
            report_md_path = task_dir / f"matrix_report_{ts}.md"
            matrix_csv_path = task_dir / f"matrix_results_{ts}.csv"

            with summary_path.open("w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)

            with report_md_path.open("w", encoding="utf-8") as f:
                f.write(render_matrix_report(results_matrix))

            with matrix_csv_path.open("w", encoding="utf-8") as f:
                f.write(generate_matrix_csv(results_matrix))

            return {
                "summary": summary,
                "files": {
                    "summary_path": str(summary_path),
                    "details_jsonl_path": None,
                    "report_md_path": str(report_md_path),
                    "report_html_path": None,
                    "matrix_csv_path": str(matrix_csv_path),
                },
            }

        summary = await tester.run()
        summary_path = task_dir / f"summary_{ts}.json"
        detail_path = task_dir / f"details_{ts}.jsonl"
        report_md_path = task_dir / f"report_{ts}.md"
        report_html_path = task_dir / f"report_{ts}.html"

        with summary_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        with detail_path.open("w", encoding="utf-8") as f:
            for item in tester.results:
                f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

        with report_md_path.open("w", encoding="utf-8") as f:
            f.write(render_markdown_report(summary))

        with report_html_path.open("w", encoding="utf-8") as f:
            f.write(render_html_report(summary, tester.results))

        return {
            "summary": summary,
            "files": {
                "summary_path": str(summary_path),
                "details_jsonl_path": str(detail_path),
                "report_md_path": str(report_md_path),
                "report_html_path": str(report_html_path),
                "matrix_csv_path": None,
            },
        }

    def _safe_config(self, args: argparse.Namespace) -> dict[str, Any]:
        data = vars(args).copy()
        data.pop("api_key", None)
        return data
