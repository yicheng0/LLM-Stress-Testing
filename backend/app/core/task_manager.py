from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.app.config import settings
from backend.app.core.progress import ProgressHub
from backend.app.core.preflight import PreflightError, validate_api_credentials
from backend.app.core.repository import Repository, _model_dump
from backend.app.core.test_runner import WebTestRunner
from backend.app.models.schemas import TestCreate


def _parse_csv_ints(value: str, field_name: str) -> list[int]:
    try:
        items = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是逗号分隔的整数") from exc
    if not items:
        raise ValueError(f"{field_name} 不能为空")
    if any(item <= 0 for item in items):
        raise ValueError(f"{field_name} 必须全部大于 0")
    return items


class TaskManager:
    def __init__(self, repository: Repository, progress_hub: ProgressHub) -> None:
        self.repository = repository
        self.progress_hub = progress_hub
        self.tasks: dict[str, asyncio.Task] = {}
        self.stop_events: dict[str, asyncio.Event] = {}

    def running_count(self) -> int:
        self._discard_finished_tasks()
        return sum(1 for task in self.tasks.values() if not task.done())

    def reconcile_active_tasks(self) -> int:
        self._discard_finished_tasks()
        live_task_ids = {task_id for task_id, task in self.tasks.items() if not task.done()}
        stale_task_ids = [
            task.id
            for task in self.repository.list_active_tasks()
            if task.id not in live_task_ids
        ]
        self.repository.mark_tasks_interrupted(stale_task_ids)
        return len(live_task_ids)

    def _discard_finished_tasks(self) -> None:
        finished_task_ids = [
            task_id
            for task_id, task in self.tasks.items()
            if task.done()
        ]
        for task_id in finished_task_ids:
            self.tasks.pop(task_id, None)
            self.stop_events.pop(task_id, None)

    async def start_test(self, payload: TestCreate) -> str:
        max_concurrency = payload.concurrency
        if payload.matrix_mode:
            input_tokens_list = _parse_csv_ints(payload.input_tokens_list, "input_tokens_list")
            concurrency_list = _parse_csv_ints(payload.concurrency_list, "concurrency_list")
            if len(input_tokens_list) * len(concurrency_list) > 25:
                raise ValueError("矩阵测试点不能超过 25 个")
            max_concurrency = max(concurrency_list)

        if max_concurrency > settings.max_concurrency_per_test:
            raise ValueError(f"单次测试并发不能超过 {settings.max_concurrency_per_test}")
        if self.running_count() >= settings.max_running_tests:
            raise ValueError(f"同时运行任务数不能超过 {settings.max_running_tests}")

        try:
            preflight = await validate_api_credentials(_model_dump(payload))
        except PreflightError as exc:
            raise ValueError(str(exc)) from exc
        if not preflight.ok:
            raise ValueError(preflight.message or "API Key 无效或无权限，无法启动测试")

        task_id = str(uuid4())
        self.repository.create_task(task_id, payload)
        self.repository.add_event(task_id, "info", "任务已创建")

        stop_event = asyncio.Event()
        self.stop_events[task_id] = stop_event

        config = _model_dump(payload)
        task = asyncio.create_task(self._run_test(task_id, config, stop_event))
        self.tasks[task_id] = task
        return task_id

    async def stop_test(self, task_id: str) -> bool:
        stop_event = self.stop_events.get(task_id)
        if not stop_event:
            return False
        stop_event.set()
        self.repository.update_task_status(task_id, "stopping")
        self.repository.add_event(task_id, "warning", "用户请求停止任务")
        await self.progress_hub.publish_status(task_id, "stopping")
        await self.progress_hub.publish_log(task_id, "warning", "用户请求停止任务")
        return True

    async def _run_test(self, task_id: str, config: dict[str, Any], stop_event: asyncio.Event) -> None:
        async def on_progress(data: dict[str, Any]) -> None:
            await self.progress_hub.publish_progress(task_id, data)

        async def on_log(level: str, message: str) -> None:
            self.repository.add_event(task_id, level, message)
            await self.progress_hub.publish_log(task_id, level, message)

        try:
            self.repository.update_task_status(task_id, "running", started_at=datetime.utcnow())
            self.repository.add_event(task_id, "info", "任务开始运行")
            await self.progress_hub.publish_status(task_id, "running")

            runner = WebTestRunner(
                task_id,
                config,
                settings.results_dir,
                progress_callback=on_progress,
                stop_event=stop_event,
                log_callback=on_log,
            )
            result = await runner.run()
            files = result["files"]
            final_status = self._final_status_from_summary(result.get("summary"))
            self.repository.save_result(
                task_id,
                summary=result["summary"],
                summary_path=files["summary_path"],
                details_jsonl_path=files["details_jsonl_path"],
                report_md_path=files["report_md_path"],
                report_html_path=files["report_html_path"],
                matrix_csv_path=files["matrix_csv_path"],
                error_message=self._final_error_message(result.get("summary")) if final_status == "failed" else None,
            )
            if stop_event.is_set():
                final_status = "cancelled"
            self.repository.update_task_status(task_id, final_status, completed_at=datetime.utcnow())
            self.repository.add_event(task_id, "info", f"任务已{final_status}")
            await self.progress_hub.publish_status(task_id, final_status)
        except Exception as exc:
            message = str(exc)
            self.repository.save_result(task_id, error_message=message)
            self.repository.update_task_status(task_id, "failed", completed_at=datetime.utcnow())
            self.repository.add_event(task_id, "error", message)
            await self.progress_hub.publish_status(task_id, "failed")
            await self.progress_hub.publish_log(task_id, "error", message)
        finally:
            self.stop_events.pop(task_id, None)
            self.tasks.pop(task_id, None)

    @staticmethod
    def _summary_results(summary: dict[str, Any] | None) -> dict[str, Any]:
        if not summary:
            return {}
        if summary.get("matrix"):
            points = summary.get("results_matrix") or []
            if not points:
                return {}
            merged_errors: dict[str, int] = {}
            total_requests = 0
            successful_requests = 0
            best_tpm = 0.0
            for point in points:
                results = point.get("results") or {}
                total_requests += int(results.get("total_requests") or 0)
                successful_requests += int(results.get("successful_requests") or 0)
                best_tpm = max(best_tpm, float(results.get("total_tpm") or 0))
                for key, value in (results.get("error_counts") or {}).items():
                    merged_errors[key] = merged_errors.get(key, 0) + int(value or 0)
            return {
                "total_requests": total_requests,
                "successful_requests": successful_requests,
                "success_rate": successful_requests / total_requests if total_requests else None,
                "total_tpm": best_tpm,
                "error_counts": merged_errors,
            }
        return summary.get("results") or {}

    @classmethod
    def _final_status_from_summary(cls, summary: dict[str, Any] | None) -> str:
        results = cls._summary_results(summary)
        total_requests = int(results.get("total_requests") or 0)
        successful_requests = int(results.get("successful_requests") or 0)
        if total_requests > 0 and successful_requests == 0:
            return "failed"
        return "completed"

    @classmethod
    def _final_error_message(cls, summary: dict[str, Any] | None) -> str | None:
        results = cls._summary_results(summary)
        error_counts = results.get("error_counts") or {}
        if error_counts.get("HTTP_401") or error_counts.get("HTTP_403"):
            return "API Key 无效或无权限"
        if int(results.get("total_requests") or 0) > 0 and int(results.get("successful_requests") or 0) == 0:
            return "本次测试全部请求失败"
        return None
