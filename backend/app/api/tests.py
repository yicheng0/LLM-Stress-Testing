from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.core.progress import ProgressHub
from backend.app.core.report_service import build_chart_data, load_details
from backend.app.core.repository import Repository
from backend.app.core.task_manager import TaskManager
from backend.app.models.database import TestEvent, TestResult, TestTask
from backend.app.models.schemas import CleanupOut, DetailsOut, EventOut, ReportOut, StartTestOut, TestCreate, TestListOut, TestTaskOut

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


def _config(task: TestTask) -> dict[str, Any]:
    try:
        return json.loads(task.config_json)
    except json.JSONDecodeError:
        return {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _summary_results(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    if summary.get("matrix"):
        points = summary.get("results_matrix") or []
        if not points:
            return {}
        best_tpm = max((_num(point.get("results", {}).get("total_tpm")) for point in points), default=0.0)
        best_rpm = max((_num(point.get("results", {}).get("rpm")) for point in points), default=0.0)
        success_rates = [
            _num(point.get("results", {}).get("success_rate"))
            for point in points
            if point.get("results", {}).get("success_rate") is not None
        ]
        p95_values = [
            _num(point.get("results", {}).get("latency_sec_p95"))
            for point in points
            if point.get("results", {}).get("latency_sec_p95") is not None
        ]
        return {
            "rpm": best_rpm,
            "total_tpm": best_tpm,
            "success_rate": sum(success_rates) / len(success_rates) if success_rates else None,
            "latency_sec_p95": max(p95_values) if p95_values else None,
        }
    return summary.get("results") or {}


def _expected_targets(expected_metrics: dict[str, Any] | None) -> dict[str, float | None]:
    expected_metrics = expected_metrics or {}
    return {
        "rpm": _num(expected_metrics.get("expected_rpm"), None),
        "tpm": _num(expected_metrics.get("expected_tpm"), None),
        "tps": _num(expected_metrics.get("expected_tps"), None),
        "latency_sec": _num(expected_metrics.get("expected_latency_sec"), None),
    }


def _achievement_ratio(current: Any, target: Any) -> float | None:
    current_value = _num(current, None)
    target_value = _num(target, None)
    if current_value is None or not target_value:
        return None
    return current_value / target_value


def _task_issue_tags(
    status: str,
    metrics: dict[str, Any],
    targets: dict[str, float | None],
    error_message: str | None,
) -> list[str]:
    tags: list[str] = []
    success_rate = _num(metrics.get("success_rate"), None)
    latency_p95 = _num(metrics.get("latency_p95"), None)
    rpm_ratio = _achievement_ratio(metrics.get("rpm"), targets.get("rpm"))
    tpm_ratio = _achievement_ratio(metrics.get("tpm"), targets.get("tpm"))
    expected_latency = targets.get("latency_sec")

    if status in {"queued", "running", "stopping"}:
        tags.append("运行中")
    if status in {"failed", "interrupted", "cancelled"}:
        tags.append("异常结束")
    if error_message:
        tags.append("有错误")
    if success_rate is not None and success_rate < 0.95:
        tags.append("低成功率")
    if latency_p95 is not None and expected_latency and latency_p95 > expected_latency * 1.25:
        tags.append("延迟高")
    if rpm_ratio is not None and rpm_ratio < 0.8:
        tags.append("RPM低")
    if tpm_ratio is not None and tpm_ratio < 0.8:
        tags.append("TPM低")
    return tags[:4]


def _dashboard_diagnostics(
    *,
    total: int,
    active_tasks: int,
    rpm: float,
    tpm: float,
    expected_rpm: float,
    expected_tpm: float,
    expected_latency_values: list[float],
    success_rates: list[float],
    p95_values: list[float],
    failed_count: int,
    error_counts: dict[str, int],
) -> dict[str, Any]:
    if total == 0:
        return {
            "overall_status": "idle",
            "summary": "暂无测试数据，启动一次压测后可查看实时诊断。",
            "reasons": [],
            "actions": [{"type": "new_test", "label": "新建测试"}],
        }

    reasons: list[str] = []
    actions: list[dict[str, str]] = []
    rpm_ratio = _achievement_ratio(rpm, expected_rpm)
    tpm_ratio = _achievement_ratio(tpm, expected_tpm)
    success_rate = sum(success_rates) / len(success_rates) if success_rates else None
    p95 = max(p95_values) if p95_values else None
    expected_latency = sum(expected_latency_values) / len(expected_latency_values) if expected_latency_values else None

    if failed_count:
        reasons.append(f"存在 {failed_count} 个失败或中断任务")
        actions.append({"type": "focus_failed", "label": "查看失败任务"})
    if error_counts:
        top_error, count = max(error_counts.items(), key=lambda item: item[1])
        reasons.append(f"主要异常为 {top_error}，出现 {count} 次")
    if success_rate is not None and success_rate < 0.95:
        reasons.append(f"成功率偏低，当前 {success_rate * 100:.1f}%")
        actions.append({"type": "focus_failed", "label": "定位失败原因"})
    if rpm_ratio is not None and rpm_ratio < 0.9:
        reasons.append(f"RPM 未达目标，当前达成 {rpm_ratio * 100:.0f}%")
        actions.append({"type": "new_test", "label": "调整并发重测"})
    if tpm_ratio is not None and tpm_ratio < 0.9:
        reasons.append(f"TPM 未达目标，当前达成 {tpm_ratio * 100:.0f}%")
        actions.append({"type": "new_test", "label": "调整配置重测"})
    if p95 is not None and expected_latency and p95 > expected_latency * 1.25:
        reasons.append(f"P95 延迟高于预期，当前 {p95:.2f}s")
        actions.append({"type": "open_report", "label": "打开最新报告"})

    if not reasons:
        summary = "实时吞吐、成功率和延迟处于可接受范围。"
        overall_status = "healthy"
    else:
        severe = failed_count > 0 or (success_rate is not None and success_rate < 0.9)
        severe = severe or any(ratio is not None and ratio < 0.6 for ratio in [rpm_ratio, tpm_ratio])
        overall_status = "critical" if severe else "warning"
        summary = reasons[0] if active_tasks else f"最近任务需要关注：{reasons[0]}"

    if not actions:
        actions.append({"type": "open_report", "label": "查看最新报告"})

    unique_actions: list[dict[str, str]] = []
    seen_actions = set()
    for action in actions:
        key = action["type"]
        if key in seen_actions:
            continue
        seen_actions.add(key)
        unique_actions.append(action)

    return {
        "overall_status": overall_status,
        "summary": summary,
        "reasons": reasons[:5],
        "actions": unique_actions[:3],
    }


def _task_out(
    task: TestTask,
    result: TestResult | None,
    progress: dict[str, Any] | None = None,
) -> TestTaskOut:
    config = _config(task)
    return TestTaskOut(
        id=task.id,
        name=task.name,
        api_protocol=task.api_protocol or config.get("api_protocol", "openai"),
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
        expected_metrics=config.get("expected_metrics"),
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        expires_at=_expires_at(task),
        progress=progress,
        summary=_safe_load_summary(result),
        error_message=result.error_message if result else None,
    )


def _event_out(event: TestEvent) -> EventOut:
    return EventOut(id=event.id, level=event.level, message=event.message, created_at=event.created_at)


def _expires_at(task: TestTask) -> datetime | None:
    if not task.completed_at:
        return None
    if settings.result_retention_hours <= 0:
        return task.completed_at
    return task.completed_at + timedelta(hours=settings.result_retention_hours)


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


@router.get("/dashboard/realtime")
async def realtime_dashboard(
    repository: Repository = Depends(get_repository),
    progress_hub: ProgressHub = Depends(get_progress_hub),
) -> dict[str, Any]:
    total, rows = repository.list_tasks(1, 100)
    status_counts: dict[str, int] = {}
    protocol_counts = {"openai": 0, "anthropic": 0, "gemini": 0}
    model_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    active_statuses = {"queued", "running", "stopping"}
    active_tasks = 0
    metric_sources: list[dict[str, Any]] = []
    fallback_metric_sources: list[dict[str, Any]] = []
    target_sources: list[dict[str, float | None]] = []
    fallback_target_sources: list[dict[str, float | None]] = []
    recent_tasks = []

    for task, result in rows:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1
        config = _config(task)
        expected_metrics = config.get("expected_metrics") or {}
        targets = _expected_targets(expected_metrics)
        protocol = task.api_protocol or config.get("api_protocol", "openai")
        protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1
        model_counts[task.model] = model_counts.get(task.model, 0) + 1
        if result and result.error_message:
            error_type = result.error_message.split(":", 1)[0][:80] or "unknown"
            error_counts[error_type] = error_counts.get(error_type, 0) + 1

        progress = progress_hub.snapshot(task.id) or {}
        summary = _safe_load_summary(result)
        summary_results = _summary_results(summary)
        is_active = task.status in active_statuses
        if is_active:
            active_tasks += 1

        item_rpm = _num(progress.get("current_rpm"), _num(summary_results.get("rpm")))
        item_tpm = _num(progress.get("current_tpm"), _num(summary_results.get("total_tpm")))
        item_success_rate = progress.get("success_rate", summary_results.get("success_rate"))
        item_p95 = progress.get("latency_sec_p95", summary_results.get("latency_sec_p95"))
        metric_item = {
            "rpm": item_rpm,
            "tpm": item_tpm,
            "success_rate": item_success_rate,
            "latency_p95": item_p95,
        }
        error_message = result.error_message if result else None
        if is_active:
            metric_sources.append(metric_item)
            target_sources.append(targets)
        fallback_metric_sources.append(metric_item)
        fallback_target_sources.append(targets)

        recent_tasks.append({
            "id": task.id,
            "name": task.name,
            "status": task.status,
            "api_protocol": protocol,
            "model": task.model,
            "concurrency": task.concurrency,
            "duration_sec": task.duration_sec,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "rpm": item_rpm,
            "tpm": item_tpm,
            "success_rate": item_success_rate,
            "latency_p95": item_p95,
            "expected_metrics": expected_metrics,
            "error_message": error_message,
            "issue_tags": _task_issue_tags(task.status, metric_item, targets, error_message),
        })

    sources = metric_sources or fallback_metric_sources[:12]
    target_sources = target_sources or fallback_target_sources[:12]
    rpm = sum(_num(item.get("rpm")) for item in sources)
    tpm = sum(_num(item.get("tpm")) for item in sources)
    expected_rpm = sum(_num(item.get("rpm")) for item in target_sources if item.get("rpm") is not None)
    expected_tpm = sum(_num(item.get("tpm")) for item in target_sources if item.get("tpm") is not None)
    expected_tps = sum(_num(item.get("tps")) for item in target_sources if item.get("tps") is not None)
    expected_latency_values = [
        _num(item.get("latency_sec"))
        for item in target_sources
        if item.get("latency_sec") is not None
    ]
    success_rates = [
        _num(item.get("success_rate"))
        for item in sources
        if item.get("success_rate") is not None
    ]
    p95_values = [
        _num(item.get("latency_p95"))
        for item in sources
        if item.get("latency_p95") is not None
    ]
    failed_count = status_counts.get("failed", 0) + status_counts.get("interrupted", 0)

    return {
        "generated_at": datetime.utcnow(),
        "total": total,
        "active_tasks": active_tasks,
        "metrics": {
            "rpm": round(rpm, 4),
            "tpm": round(tpm, 4),
            "expected_rpm": round(expected_rpm, 4) if expected_rpm else None,
            "expected_tpm": round(expected_tpm, 4) if expected_tpm else None,
            "expected_tps": round(expected_tps, 4) if expected_tps else None,
            "expected_latency_sec": round(sum(expected_latency_values) / len(expected_latency_values), 4) if expected_latency_values else None,
            "success_rate": round(sum(success_rates) / len(success_rates), 4) if success_rates else None,
            "latency_p95": round(max(p95_values), 4) if p95_values else None,
        },
        "status_counts": status_counts,
        "protocol_counts": protocol_counts,
        "model_counts": dict(sorted(model_counts.items(), key=lambda item: item[1], reverse=True)[:8]),
        "error_counts": dict(sorted(error_counts.items(), key=lambda item: item[1], reverse=True)[:8]),
        "diagnostics": _dashboard_diagnostics(
            total=total,
            active_tasks=active_tasks,
            rpm=rpm,
            tpm=tpm,
            expected_rpm=expected_rpm,
            expected_tpm=expected_tpm,
            expected_latency_values=expected_latency_values,
            success_rates=success_rates,
            p95_values=p95_values,
            failed_count=failed_count,
            error_counts=error_counts,
        ),
        "recent_tasks": recent_tasks[:8],
    }


@router.post("/cleanup/expired", response_model=CleanupOut)
async def cleanup_expired(repository: Repository = Depends(get_repository)) -> CleanupOut:
    deleted = repository.cleanup_expired_results()
    return CleanupOut(deleted=deleted, retention_hours=settings.result_retention_hours)


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
    return ReportOut(
        test_id=task_id,
        config=config,
        summary=summary,
        charts=charts,
        files=files,
        events=events,
        completed_at=task.completed_at,
        expires_at=_expires_at(task),
        retention_hours=settings.result_retention_hours,
    )


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
