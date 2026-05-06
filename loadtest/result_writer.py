from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import RequestResult
from .reports import generate_matrix_csv, render_html_report, render_markdown_report, render_matrix_report


class ReportArtifactWriter:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_single(self, summary: dict[str, Any], details: list[RequestResult]) -> dict[str, str]:
        ts = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.output_dir / f"summary_{ts}.json"
        detail_path = self.output_dir / f"details_{ts}.jsonl"
        report_path = self.output_dir / f"report_{ts}.md"
        html_path = self.output_dir / f"report_{ts}.html"

        self.write_json(summary_path, summary)
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
        }

    def write_matrix(self, results_matrix: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> dict[str, str | None]:
        ts = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.output_dir / f"matrix_summary_{ts}.json"
        report_path = self.output_dir / f"matrix_report_{ts}.md"
        csv_path = self.output_dir / f"matrix_results_{ts}.csv"

        self.write_json(summary_path, summary if summary is not None else results_matrix)
        report_path.write_text(render_matrix_report(results_matrix), encoding="utf-8")
        csv_path.write_text(generate_matrix_csv(results_matrix), encoding="utf-8")

        return {
            "summary_path": str(summary_path),
            "details_jsonl_path": None,
            "report_md_path": str(report_path),
            "report_html_path": None,
            "matrix_csv_path": str(csv_path),
        }

    @staticmethod
    def write_json(path: Path, data: Any) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
