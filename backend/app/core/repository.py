from __future__ import annotations

import json
import shutil
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.database import SessionLocal, TestEvent, TestResult, TestTask
from backend.app.models.schemas import TestCreate


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class Repository:
    def session(self) -> Session:
        return SessionLocal()

    def create_task(self, task_id: str, payload: TestCreate) -> TestTask:
        data = _model_dump(payload)
        data.pop("api_key", None)
        now = datetime.utcnow()
        task = TestTask(
            id=task_id,
            name=payload.name,
            base_url=payload.base_url,
            endpoint=payload.endpoint,
            model=payload.model,
            status="queued",
            concurrency=payload.concurrency,
            duration_sec=payload.duration_sec,
            input_tokens=payload.input_tokens,
            max_output_tokens=payload.max_output_tokens,
            enable_stream=payload.enable_stream,
            matrix_mode=payload.matrix_mode,
            config_json=json.dumps(data, ensure_ascii=False),
            created_at=now,
        )
        with self.session() as db:
            db.add(task)
            db.add(TestResult(task_id=task_id))
            db.commit()
            db.refresh(task)
            return task

    def get_task(self, task_id: str) -> tuple[TestTask, TestResult | None] | None:
        with self.session() as db:
            task = db.get(TestTask, task_id)
            if not task:
                return None
            result = db.get(TestResult, task_id)
            db.expunge(task)
            if result:
                db.expunge(result)
            return task, result

    def list_tasks(
        self,
        page: int,
        page_size: int,
        status: str | None = None,
        model: str | None = None,
        api_protocol: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[int, list[tuple[TestTask, TestResult | None]]]:
        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        with self.session() as db:
            filters = []
            if status:
                filters.append(TestTask.status == status)
            if model:
                filters.append(TestTask.model == model)
            if created_from:
                filters.append(TestTask.created_at >= created_from)
            if created_to:
                filters.append(TestTask.created_at <= created_to)

            base_stmt = (
                select(TestTask, TestResult)
                .outerjoin(TestResult, TestTask.id == TestResult.task_id)
                .where(*filters)
                .order_by(TestTask.created_at.desc())
            )

            if api_protocol:
                rows = db.execute(base_stmt).all()
                protocol_rows = []
                for task, result in rows:
                    try:
                        protocol = json.loads(task.config_json).get("api_protocol", "openai")
                    except json.JSONDecodeError:
                        protocol = "openai"
                    if protocol == api_protocol:
                        protocol_rows.append((task, result))
                total = len(protocol_rows)
                rows = protocol_rows[(page - 1) * page_size : page * page_size]
            else:
                total_stmt = select(func.count()).select_from(TestTask).where(*filters)
                total = int(db.execute(total_stmt).scalar_one())
                rows = db.execute(
                    base_stmt.offset((page - 1) * page_size).limit(page_size)
                ).all()

            items: list[tuple[TestTask, TestResult | None]] = []
            for task, result in rows:
                db.expunge(task)
                if result:
                    db.expunge(result)
                items.append((task, result))
            return total, items

    def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        with self.session() as db:
            task = db.get(TestTask, task_id)
            if not task:
                return
            task.status = status
            if started_at is not None:
                task.started_at = started_at
            if completed_at is not None:
                task.completed_at = completed_at
            db.commit()

    def save_result(
        self,
        task_id: str,
        *,
        summary: dict[str, Any] | None = None,
        error_message: str | None = None,
        summary_path: str | None = None,
        details_jsonl_path: str | None = None,
        report_md_path: str | None = None,
        report_html_path: str | None = None,
        matrix_csv_path: str | None = None,
    ) -> None:
        with self.session() as db:
            result = db.get(TestResult, task_id)
            if result is None:
                result = TestResult(task_id=task_id)
                db.add(result)
            if summary is not None:
                result.summary_json = json.dumps(summary, ensure_ascii=False)
            if error_message is not None:
                result.error_message = error_message
            result.summary_path = summary_path or result.summary_path
            result.details_jsonl_path = details_jsonl_path or result.details_jsonl_path
            result.report_md_path = report_md_path or result.report_md_path
            result.report_html_path = report_html_path or result.report_html_path
            result.matrix_csv_path = matrix_csv_path or result.matrix_csv_path
            db.commit()

    def add_event(self, task_id: str, level: str, message: str) -> None:
        with self.session() as db:
            db.add(TestEvent(task_id=task_id, level=level, message=message[:4000]))
            db.commit()

    def list_events(self, task_id: str, limit: int = 50) -> list[TestEvent]:
        with self.session() as db:
            stmt = (
                select(TestEvent)
                .where(TestEvent.task_id == task_id)
                .order_by(TestEvent.created_at.desc())
                .limit(limit)
            )
            rows = list(db.execute(stmt).scalars())
            for row in rows:
                db.expunge(row)
            return list(reversed(rows))

    def mark_unfinished_interrupted(self) -> None:
        with self.session() as db:
            stmt = select(TestTask).where(TestTask.status.in_(["queued", "running", "stopping"]))
            for task in db.execute(stmt).scalars():
                task.status = "interrupted"
                task.completed_at = datetime.utcnow()
            db.commit()

    def delete_task(self, task_id: str) -> bool:
        task_results_dir = (settings.results_dir / task_id).resolve()
        results_root = settings.results_dir.resolve()
        with self.session() as db:
            task = db.get(TestTask, task_id)
            if not task:
                return False
            for event in db.execute(select(TestEvent).where(TestEvent.task_id == task_id)).scalars():
                db.delete(event)
            result = db.get(TestResult, task_id)
            if result:
                db.delete(result)
            db.delete(task)
            db.commit()
        if task_results_dir.exists() and results_root in task_results_dir.parents:
            shutil.rmtree(task_results_dir)
        return True
