from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.database import SessionLocal, TestEvent, TestResult, TestTask
from backend.app.models.schemas import TestCreate


SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key['\"\s:=]+)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)((?:x-api-key|x-goog-api-key)['\"\s:=]+)[A-Za-z0-9._\-]{12,}"),
]


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]", redacted)
    return redacted


def _redact_sensitive(data: Any) -> Any:
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            if key.lower() in {"api_key", "api-key", "authorization", "x-api-key", "x-goog-api-key"}:
                continue
            redacted[key] = _redact_sensitive(value)
        return redacted
    if isinstance(data, list):
        return [_redact_sensitive(item) for item in data]
    if isinstance(data, str):
        return _redact_text(data)
    return data


class Repository:
    def session(self) -> Session:
        return SessionLocal()

    def create_task(self, task_id: str, payload: TestCreate) -> TestTask:
        data = _redact_sensitive(_model_dump(payload))
        now = datetime.utcnow()
        task = TestTask(
            id=task_id,
            name=payload.name,
            api_protocol=payload.api_protocol,
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
            if api_protocol:
                filters.append(TestTask.api_protocol == api_protocol)
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
                result.summary_json = json.dumps(_redact_sensitive(summary), ensure_ascii=False)
            if error_message is not None:
                result.error_message = _redact_text(error_message)
            result.summary_path = summary_path or result.summary_path
            result.details_jsonl_path = details_jsonl_path or result.details_jsonl_path
            result.report_md_path = report_md_path or result.report_md_path
            result.report_html_path = report_html_path or result.report_html_path
            result.matrix_csv_path = matrix_csv_path or result.matrix_csv_path
            db.commit()

    def add_event(self, task_id: str, level: str, message: str) -> None:
        with self.session() as db:
            db.add(TestEvent(task_id=task_id, level=level, message=_redact_text(message)[:4000]))
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

    def cleanup_expired_results(self, retention_hours: int | None = None) -> int:
        retention = settings.result_retention_hours if retention_hours is None else retention_hours
        if retention <= 0:
            cutoff = datetime.utcnow()
        else:
            cutoff = datetime.utcnow() - timedelta(hours=retention)

        terminal_statuses = ["completed", "failed", "cancelled", "interrupted"]
        with self.session() as db:
            stmt = select(TestTask.id).where(
                TestTask.status.in_(terminal_statuses),
                TestTask.completed_at.is_not(None),
                TestTask.completed_at < cutoff,
            )
            task_ids = [row[0] for row in db.execute(stmt).all()]

        deleted = 0
        for task_id in task_ids:
            if self.delete_task(task_id):
                deleted += 1
        return deleted
