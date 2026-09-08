from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException
from backend.app.api.tests import _ensure_base_url_allowed, _ensure_task_access, _event_out, get_progress_hub, get_repository, get_task_manager
from backend.app.core.auth import AuthUser, current_user
from backend.app.core.progress import ProgressHub
from backend.app.core.repository import Repository, _model_dump
from backend.app.core.task_manager import TaskManager
from backend.app.models.schemas import KimiSuiteCreate, StartTestOut

router = APIRouter(prefix="/api/kimi-suite", tags=["kimi-suite"])

@router.post("", response_model=StartTestOut)
async def start(payload: KimiSuiteCreate, user: AuthUser = Depends(current_user), repository: Repository = Depends(get_repository), manager: TaskManager = Depends(get_task_manager)):
    _ensure_base_url_allowed(payload.base_url, user)
    try: task_id = await manager.start_kimi_suite(payload, user)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    item = repository.get_task(task_id)
    if not item: raise HTTPException(status_code=500, detail="任务创建后无法读取")
    task, _ = item
    return StartTestOut(test_id=task.id, status=task.status, created_at=task.created_at)

@router.get("/{task_id}")
async def get(task_id: str, user: AuthUser = Depends(current_user), repository: Repository = Depends(get_repository), progress_hub: ProgressHub = Depends(get_progress_hub)):
    item = repository.get_task(task_id)
    if not item: raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item; _ensure_task_access(task, user)
    config = json.loads(task.config_json)
    if config.get("task_kind") != "kimi_suite": raise HTTPException(status_code=400, detail="任务类型不匹配")
    summary = json.loads(result.summary_json) if result and result.summary_json else None
    return {"test_id": task.id, "task_status": task.status, "config": config, "progress": progress_hub.snapshot(task.id), "summary": summary, "events": [_event_out(e) for e in repository.list_events(task_id)], "created_at": task.created_at, "started_at": task.started_at, "completed_at": task.completed_at}
