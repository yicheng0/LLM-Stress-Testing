from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .chart_data import ChartDataAccumulator, build_matrix_chart_data, build_single_chart_data
from .models import RequestResult
from .reports import generate_matrix_csv, render_html_report, render_markdown_report, render_matrix_report


class StreamingResultCollector:
    def __init__(self, output_dir: str | Path, *, report_sample_limit: int = 5000) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.detail_path = self.output_dir / f"details_{ts}.jsonl"
        self._detail_file = self.detail_path.open("w", encoding="utf-8")
        self._closed = False
        self.charts = ChartDataAccumulator()
        self.report_samples: list[RequestResult] = []
        self.report_sample_limit = report_sample_limit

    def record(self, item: RequestResult) -> None:
        self._detail_file.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
        self.charts.record(item)
        if len(self.report_samples) < self.report_sample_limit:
            self.report_samples.append(item)

    def close(self) -> None:
        if not self._closed:
            self._detail_file.close()
            self._closed = True

    @property
    def detail_count(self) -> int:
        return self.charts.detail_count

    def build_charts(self) -> dict[str, Any]:
        return self.charts.build()


class ReportArtifactWriter:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_single(self, summary: dict[str, Any], details: list[RequestResult]) -> dict[str, str]:
        ts = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.output_dir / f"summary_{ts}.json"
        detail_path = self.output_dir / f"details_{ts}.jsonl"
        charts_path = self.output_dir / f"charts_{ts}.json"
        report_path = self.output_dir / f"report_{ts}.md"
        html_path = self.output_dir / f"report_{ts}.html"

        self.write_json(summary_path, summary)
        self.write_json(charts_path, build_single_chart_data(details))
        with detail_path.open("w", encoding="utf-8") as f:
            for item in details:
                f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
        report_path.write_text(render_markdown_report(summary), encoding="utf-8")
        html_path.write_text(render_html_report(summary, details), encoding="utf-8")

        return {
            "summary_path": str(summary_path),
            "details_jsonl_path": str(detail_path),
            "report_md_path": str(report_path),
            "report_html_path": str(html_path),
            "matrix_csv_path": None,
            "charts_path": str(charts_path),
            "detail_count": len(details),
        }

    def write_single_from_collector(self, summary: dict[str, Any], collector: StreamingResultCollector) -> dict[str, str | int | None]:
        ts = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.output_dir / f"summary_{ts}.json"
        charts_path = self.output_dir / f"charts_{ts}.json"
        report_path = self.output_dir / f"report_{ts}.md"
        html_path = self.output_dir / f"report_{ts}.html"

        collector.close()
        self.write_json(summary_path, summary)
        self.write_json(charts_path, collector.build_charts())
        report_path.write_text(render_markdown_report(summary), encoding="utf-8")
        html_path.write_text(render_html_report(summary, collector.report_samples), encoding="utf-8")

        return {
            "summary_path": str(summary_path),
            "details_jsonl_path": str(collector.detail_path),
            "report_md_path": str(report_path),
            "report_html_path": str(html_path),
            "matrix_csv_path": None,
            "charts_path": str(charts_path),
            "detail_count": collector.detail_count,
        }

    def write_matrix(self, results_matrix: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> dict[str, str | None]:
        ts = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.output_dir / f"matrix_summary_{ts}.json"
        charts_path = self.output_dir / f"matrix_charts_{ts}.json"
        report_path = self.output_dir / f"matrix_report_{ts}.md"
        csv_path = self.output_dir / f"matrix_results_{ts}.csv"

        self.write_json(summary_path, summary if summary is not None else results_matrix)
        self.write_json(charts_path, build_matrix_chart_data(results_matrix))
        report_path.write_text(render_matrix_report(results_matrix), encoding="utf-8")
        csv_path.write_text(generate_matrix_csv(results_matrix), encoding="utf-8")

        return {
            "summary_path": str(summary_path),
            "details_jsonl_path": None,
            "report_md_path": str(report_path),
            "report_html_path": None,
            "matrix_csv_path": str(csv_path),
            "charts_path": str(charts_path),
            "detail_count": 0,
        }

    @staticmethod
    def write_json(path: Path, data: Any) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
