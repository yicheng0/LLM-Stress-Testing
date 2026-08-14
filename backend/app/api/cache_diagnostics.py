from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.tests import (
    _ensure_base_url_allowed,
    _ensure_task_access,
    _event_out,
    get_progress_hub,
    get_repository,
    get_task_manager,
)
from backend.app.core.auth import AuthUser, current_user
from backend.app.core.cache_diagnostics import redact_cache_text
from backend.app.core.progress import ProgressHub
from backend.app.core.repository import Repository
from backend.app.core.task_manager import TaskManager
from backend.app.models.schemas import CacheDiagnosticsCreate, CacheDiagnosticsOut, StartTestOut

router = APIRouter(prefix="/api/cache-diagnostics", tags=["cache-diagnostics"])
logger = logging.getLogger(__name__)


def _config(task) -> dict:
    try:
        return json.loads(task.config_json)
    except json.JSONDecodeError:
        return {}


def _summary(result) -> dict | None:
    if not result or not result.summary_json:
        return None
    try:
        return json.loads(result.summary_json)
    except json.JSONDecodeError:
        return None


@router.post("", response_model=StartTestOut)
async def start_cache_diagnostics(
    payload: CacheDiagnosticsCreate,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    manager: TaskManager = Depends(get_task_manager),
) -> StartTestOut:
    _ensure_base_url_allowed(payload.base_url, user)
    try:
        task_id = await manager.start_cache_diagnostics(payload, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        message = redact_cache_text(str(exc), payload.api_key)
        logger.error("Failed to start cache diagnostics: %s", message)
        raise HTTPException(status_code=502, detail=f"启动缓存专项测试失败：{message}") from exc
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=500, detail="任务创建后无法读取")
    task, _ = item
    return StartTestOut(test_id=task.id, status=task.status, created_at=task.created_at)


@router.get("/{task_id}", response_model=CacheDiagnosticsOut)
async def get_cache_diagnostics(
    task_id: str,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    progress_hub: ProgressHub = Depends(get_progress_hub),
) -> CacheDiagnosticsOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    config = _config(task)
    if config.get("task_kind") != "cache_diagnostics":
        raise HTTPException(status_code=400, detail="任务类型不匹配")
    return CacheDiagnosticsOut(
        test_id=task.id,
        task_status=task.status,
        config=config,
        progress=progress_hub.snapshot(task.id),
        summary=_summary(result),
        events=[_event_out(event) for event in repository.list_events(task.id)],
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )
