from __future__ import annotations

import json
from fnmatch import fnmatchcase
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.app.api.tests import (
    _download_user,
    _ensure_task_access,
    _expires_at,
    _event_out,
    _safe_download_file,
    _safe_load_summary,
    _safe_output_file,
    get_progress_hub,
    get_repository,
    get_task_manager,
)
from backend.app.config import settings
from backend.app.core.auth import AuthUser, current_user
from backend.app.core.pdf_report import PDF_RENDER_ERROR, ensure_pdf_report, pdf_path_for_result
from backend.app.core.vendor_billing import load_pricing_catalog, pricing_rule
from backend.app.core.vendor_endpoint_security import validate_vendor_endpoint
from backend.app.models.schemas import EventOut, ReportOut, StartTestOut, VendorBillingConfigOut, VendorBillingCreate, VendorBillingFromTemplate, VendorBillingOut

router = APIRouter(prefix="/api/vendor-billing", tags=["vendor-billing"])


def _config(task: Any) -> dict[str, Any]:
    try:
        return json.loads(task.config_json)
    except json.JSONDecodeError:
        return {}


def _summary(result: Any) -> dict[str, Any] | None:
    try:
        return json.loads(result.summary_json) if result and result.summary_json else None
    except json.JSONDecodeError:
        return None


@router.get("/config", response_model=VendorBillingConfigOut)
async def get_config(_: AuthUser = Depends(current_user)) -> VendorBillingConfigOut:
    return VendorBillingConfigOut(protocols=["openai", "anthropic", "gemini"], default_input_token_lengths=[128, 1024, 4096], pricing_rules=load_pricing_catalog())


@router.get("/pricing", response_model=list[dict[str, Any]])
async def get_pricing(_: AuthUser = Depends(current_user)) -> list[dict[str, Any]]:
    return load_pricing_catalog()


@router.post("", response_model=StartTestOut)
async def start(payload: VendorBillingCreate, user: AuthUser = Depends(current_user), manager=Depends(get_task_manager), repository=Depends(get_repository)) -> StartTestOut:
    try:
        validate_vendor_endpoint(payload.base_url)
        validate_vendor_endpoint(payload.reference_base_url, reference=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rule = pricing_rule(payload.pricing_rule_id)
    if not rule:
        raise HTTPException(status_code=400, detail="价格规则不存在，无法启动自测")
    if rule.get("protocol") != payload.api_protocol:
        raise HTTPException(status_code=400, detail="价格规则与所选 API 协议不匹配")
    pattern = str(rule.get("reference_model_pattern") or rule.get("model") or "")
    if not pattern or not fnmatchcase(payload.reference_model, pattern):
        raise HTTPException(status_code=400, detail="官方参考模型与价格规则不匹配")
    try:
        task_id = await manager.start_vendor_billing(payload, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task, _ = repository.get_task(task_id) or (None, None)
    if task is None:
        raise HTTPException(status_code=500, detail="任务创建后无法读取")
    return StartTestOut(test_id=task.id, status=task.status, created_at=task.created_at)


@router.post("/from-template", response_model=StartTestOut)
async def start_from_template(
    payload: VendorBillingFromTemplate,
    user: AuthUser = Depends(current_user),
    manager=Depends(get_task_manager),
    repository=Depends(get_repository),
) -> StartTestOut:
    template = repository.get_vendor_template(payload.template_id, user)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not template.enabled:
        raise HTTPException(status_code=409, detail="模板已停用，不能创建新任务")
    try:
        config = json.loads(template.config_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="模板配置损坏") from exc
    config.update(
        {
            "name": (payload.name or config.get("name") or "供应商接入计费自测").strip(),
            "api_key": payload.api_key,
            "reference_api_key": payload.reference_api_key,
            "template_id": template.id,
            "template_name": template.name,
            "template_version": template.version,
        }
    )
    try:
        request = VendorBillingCreate(**config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await start(request, user, manager, repository)


@router.get("/{task_id}", response_model=VendorBillingOut)
async def get_task(task_id: str, user: AuthUser = Depends(current_user), repository=Depends(get_repository), progress_hub=Depends(get_progress_hub)) -> VendorBillingOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    config = _config(task)
    if config.get("task_kind") != "vendor_billing_self_test":
        raise HTTPException(status_code=400, detail="任务类型不匹配")
    return VendorBillingOut(test_id=task.id, task_status=task.status, config=config, progress=progress_hub.snapshot(task.id), summary=_summary(result), events=[_event_out(event) for event in repository.list_events(task.id)], created_at=task.created_at, started_at=task.started_at, completed_at=task.completed_at)


def _report(task: Any, result: Any) -> ReportOut:
    config = _config(task)
    summary = _summary(result)
    files = {
        "summary": result.summary_path if result else None,
        "details": result.details_jsonl_path if result else None,
        "markdown": result.report_md_path if result else None,
        "html": result.report_html_path if result else None,
        "matrix_csv": None,
        "pdf": str(pdf_path_for_result(result.summary_path if result else None, settings.results_dir)) if result and result.summary_path else None,
    }
    return ReportOut(
        test_id=task.id,
        task_status=task.status,
        config=config,
        summary=summary,
        charts={},
        files=files,
        events=[],
        completed_at=task.completed_at,
        expires_at=_expires_at(task),
        retention_hours=settings.result_retention_hours,
    )


@router.get("/{task_id}/report", response_model=ReportOut)
async def get_vendor_report(
    task_id: str,
    user: AuthUser = Depends(current_user),
    repository=Depends(get_repository),
) -> ReportOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    if _config(task).get("task_kind") != "vendor_billing_self_test":
        raise HTTPException(status_code=400, detail="任务类型不匹配")
    report = _report(task, result)
    report.events = [_event_out(event) for event in repository.list_events(task_id)]
    return report


@router.get("/{task_id}/download/{kind}")
async def download_vendor_report(
    task_id: str,
    kind: str,
    user: AuthUser = Depends(_download_user),
    repository=Depends(get_repository),
) -> FileResponse:
    if kind not in {"summary", "details", "markdown", "html", "pdf"}:
        raise HTTPException(status_code=404, detail="不支持的下载类型")
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    if _config(task).get("task_kind") != "vendor_billing_self_test":
        raise HTTPException(status_code=400, detail="任务类型不匹配")
    if kind == "pdf":
        summary = _safe_load_summary(result) if result else None
        if not summary or not result or not result.summary_path:
            raise HTTPException(status_code=404, detail="报告文件不存在")
        output_path = _safe_output_file(pdf_path_for_result(result.summary_path, settings.results_dir))
        if not output_path:
            raise HTTPException(status_code=404, detail="报告文件不存在")
        try:
            path = ensure_pdf_report(summary=summary, details_path=result.details_jsonl_path, charts_path=None, output_path=output_path)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc) or PDF_RENDER_ERROR) from exc
        safe_path = _safe_download_file(str(path))
        if not safe_path:
            raise HTTPException(status_code=404, detail="报告文件不存在")
        return FileResponse(safe_path, media_type="application/pdf", filename=safe_path.name)
    paths = {
        "summary": result.summary_path if result else None,
        "details": result.details_jsonl_path if result else None,
        "markdown": result.report_md_path if result else None,
        "html": result.report_html_path if result else None,
    }
    path = _safe_download_file(paths[kind])
    if not path:
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(path)
