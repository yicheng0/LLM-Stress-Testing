from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.core.progress import ProgressHub
from backend.app.core.report_service import build_chart_data, load_details
from backend.app.core.repository import Repository
from backend.app.core.task_manager import TaskManager
from backend.app.models.database import TestEvent, TestResult, TestTask
from backend.app.models.schemas import DetailsOut, EventOut, ReportOut, StartTestOut, TestCreate, TestListOut, TestTaskOut

router = APIRouter(prefix="/api/tests", tags=["tests"])


def get_repository() -> Repository:
    from backend.app.main import repository

    return repository


def get_progress_hub() -> ProgressHub:
    from backend.app.main import progress_hub

    return progress_hub


def get_task_manager() -> TaskManager:
    from backend.app.main import task_manager

    return task_manager


def _summary(result: TestResult | None) -> dict[str, Any] | None:
    if not result or not result.summary_json:
        return None
    return json.loads(result.summary_json)


def _safe_load_summary(result: TestResult | None) -> dict[str, Any] | None:
    try:
        return _summary(result)
    except json.JSONDecodeError:
        return None


def _task_out(
    task: TestTask,
    result: TestResult | None,
    progress: dict[str, Any] | None = None,
) -> TestTaskOut:
    return TestTaskOut(
        id=task.id,
        name=task.name,
        api_protocol=json.loads(task.config_json).get("api_protocol", "openai"),
        base_url=task.base_url,
        endpoint=task.endpoint,
        model=task.model,
        status=task.status,
        concurrency=task.concurrency,
        duration_sec=task.duration_sec,
        input_tokens=task.input_tokens,
        max_output_tokens=task.max_output_tokens,
        enable_stream=task.enable_stream,
        matrix_mode=task.matrix_mode,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        progress=progress,
        summary=_safe_load_summary(result),
        error_message=result.error_message if result else None,
    )


def _event_out(event: TestEvent) -> EventOut:
    return EventOut(id=event.id, level=event.level, message=event.message, created_at=event.created_at)


@router.post("", response_model=StartTestOut)
async def start_test(
    payload: TestCreate,
    repository: Repository = Depends(get_repository),
    manager: TaskManager = Depends(get_task_manager),
) -> StartTestOut:
    try:
        task_id = await manager.start_test(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=500, detail="任务创建后无法读取")
    task, _ = item
    return StartTestOut(test_id=task.id, status=task.status, created_at=task.created_at)


@router.get("", response_model=TestListOut)
async def list_tests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    model: str | None = None,
    api_protocol: str | None = Query(default=None, pattern="^(openai|anthropic|gemini)$"),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    repository: Repository = Depends(get_repository),
    progress_hub: ProgressHub = Depends(get_progress_hub),
) -> TestListOut:
    total, rows = repository.list_tasks(
        page,
        page_size,
        status=status,
        model=model,
        api_protocol=api_protocol,
        created_from=created_from,
        created_to=created_to,
    )
    return TestListOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[_task_out(task, result, progress_hub.snapshot(task.id)) for task, result in rows],
    )


@router.get("/{task_id}", response_model=TestTaskOut)
async def get_test(
    task_id: str,
    repository: Repository = Depends(get_repository),
    progress_hub: ProgressHub = Depends(get_progress_hub),
) -> TestTaskOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    return _task_out(task, result, progress_hub.snapshot(task_id))


@router.post("/{task_id}/stop")
async def stop_test(task_id: str, manager: TaskManager = Depends(get_task_manager)) -> dict[str, Any]:
    stopped = await manager.stop_test(task_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="任务不存在或不在运行中")
    return {"test_id": task_id, "status": "stopping"}


@router.delete("/{task_id}")
async def delete_test(task_id: str, repository: Repository = Depends(get_repository)) -> dict[str, Any]:
    deleted = repository.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"deleted": True}


@router.get("/{task_id}/report", response_model=ReportOut)
async def get_report(task_id: str, repository: Repository = Depends(get_repository)) -> ReportOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    config = json.loads(task.config_json)
    summary = _summary(result)
    charts = build_chart_data(summary, result.details_jsonl_path if result else None)
    files = {
        "summary": result.summary_path if result else None,
        "details": result.details_jsonl_path if result else None,
        "markdown": result.report_md_path if result else None,
        "html": result.report_html_path if result else None,
        "matrix_csv": result.matrix_csv_path if result else None,
    }
    events = [_event_out(event) for event in repository.list_events(task_id)]
    return ReportOut(test_id=task_id, config=config, summary=summary, charts=charts, files=files, events=events)


@router.get("/{task_id}/details", response_model=DetailsOut)
async def get_details(
    task_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    repository: Repository = Depends(get_repository),
) -> DetailsOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    _, result = item
    total, items = load_details(result.details_jsonl_path if result else None, page=page, page_size=page_size)
    return DetailsOut(total=total, page=page, page_size=page_size, items=items)


def _download_path(result: TestResult | None, kind: str) -> str | None:
    if not result:
        return None
    return {
        "summary": result.summary_path,
        "details": result.details_jsonl_path,
        "markdown": result.report_md_path,
        "html": result.report_html_path,
        "matrix_csv": result.matrix_csv_path,
    }.get(kind)


def _safe_download_file(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path).resolve()
    results_root = settings.results_dir.resolve()
    if not candidate.exists() or results_root not in candidate.parents:
        return None
    return candidate


@router.get("/{task_id}/download/{kind}")
async def download_report(
    task_id: str,
    kind: str,
    repository: Repository = Depends(get_repository),
) -> FileResponse:
    if kind not in {"summary", "details", "markdown", "html", "matrix_csv"}:
        raise HTTPException(status_code=404, detail="不支持的下载类型")
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    _, result = item
    path = _safe_download_file(_download_path(result, kind))
    if not path:
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(path)
