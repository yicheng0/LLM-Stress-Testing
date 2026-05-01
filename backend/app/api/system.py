from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.config import settings
from backend.app.core.version_service import get_version_snapshot, run_self_update
from backend.app.models.schemas import VersionInfoOut, VersionUpdateOut, VersionUpdateRequest

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/version", response_model=VersionInfoOut)
async def get_version() -> VersionInfoOut:
    snapshot = get_version_snapshot(fetch=False)
    return VersionInfoOut(**snapshot.to_dict())


@router.post("/version/check", response_model=VersionInfoOut)
async def check_version() -> VersionInfoOut:
    try:
        snapshot = get_version_snapshot(fetch=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"检查版本失败：{exc}") from exc
    return VersionInfoOut(**snapshot.to_dict())


@router.post("/version/update", response_model=VersionUpdateOut)
async def update_version(payload: VersionUpdateRequest) -> VersionUpdateOut:
    if not settings.self_update_enabled:
        raise HTTPException(status_code=403, detail="当前环境未启用在线更新")

    try:
        snapshot = get_version_snapshot(fetch=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"检查版本失败：{exc}") from exc
    if snapshot.dirty and not payload.force:
        raise HTTPException(status_code=409, detail="工作区存在未提交修改，无法自动更新")
    if not snapshot.available:
        raise HTTPException(status_code=400, detail=snapshot.message or "当前环境无法在线更新")

    stdout, stderr = await asyncio.to_thread(run_self_update, snapshot.branch)
    refreshed = get_version_snapshot(fetch=False)
    return VersionUpdateOut(
        success=True,
        message="更新已完成",
        current_ref=refreshed.current_ref,
        latest_ref=refreshed.latest_ref,
        restart_required=True,
        stdout=stdout or None,
        stderr=stderr or None,
    )
