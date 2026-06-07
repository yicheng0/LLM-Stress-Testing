from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from backend.app.config import settings
from backend.app.core.auth import AuthUser, can_access_task, current_user, parse_token, require_root
from backend.app.core.base_url_policy import is_built_in_base_url
from backend.app.core.progress import ProgressHub
from backend.app.core.report_service import build_chart_data, load_details
from backend.app.core.repository import Repository
from backend.app.core.task_manager import TaskManager
from backend.app.models.database import TestEvent, TestResult, TestTask
from backend.app.models.schemas import BulkDeleteIn, BulkDeleteOut, CustomCaseBatchFailure, CustomCaseBatchOut, CustomCaseBatchRequest, DetailsOut, EventOut, MatrixResumeRequest, ReportOut, StartTestOut, TestCreate, TestListOut, TestTaskOut

router = APIRouter(prefix="/api/tests", tags=["tests"])
logger = logging.getLogger(__name__)


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


def _summary_from_file(result: TestResult | None) -> dict[str, Any] | None:
    path = _safe_download_file(result.summary_path if result else None)
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _matrix_results_for_resume(result: TestResult | None) -> list[dict[str, Any]]:
    summary = _safe_load_summary(result) or _summary_from_file(result)
    if not summary or not summary.get("matrix"):
        return []
    points = summary.get("results_matrix")
    return points if isinstance(points, list) else []


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _estimate_prompt_tokens(prompt: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", prompt))
    non_cjk = max(0, len(prompt) - cjk)
    return max(1, int(cjk * 1.1 + non_cjk / 4 + 0.999))


def _custom_case_expected_metrics(
    *,
    prompt: str,
    concurrency: int,
    duration_sec: int,
    max_output_tokens: int,
    think_time_ms: int,
) -> dict[str, float]:
    input_tokens = _estimate_prompt_tokens(prompt)
    effective_latency_sec = max(0.001, 10 + think_time_ms / 1000)
    expected_rpm = concurrency / effective_latency_sec * 60
    expected_requests = expected_rpm * duration_sec / 60
    expected_tpm = expected_rpm * (input_tokens + max_output_tokens)
    return {
        "expected_rpm": expected_rpm,
        "expected_tpm": expected_tpm,
        "expected_tps": expected_tpm / 60,
        "expected_requests": expected_requests,
        "expected_input_token_total": expected_requests * input_tokens,
        "expected_output_token_limit": expected_requests * max_output_tokens,
        "expected_latency_sec": 10,
    }


def _summary_results(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    if summary.get("matrix"):
        points = summary.get("results_matrix") or []
        if not points:
            return {}
        best_tpm = max((_num(point.get("results", {}).get("total_tpm")) for point in points), default=0.0)
        best_cache_hit_tpm = max((_num(point.get("results", {}).get("cache_hit_tpm")) for point in points), default=0.0)
        best_cache_inclusive_tpm = max((_num(point.get("results", {}).get("cache_inclusive_tpm")) for point in points), default=0.0)
        total_cached_input_tokens = sum(_num(point.get("results", {}).get("total_cached_input_tokens")) for point in points)
        total_cache_creation_input_tokens = sum(_num(point.get("results", {}).get("total_cache_creation_input_tokens")) for point in points)
        total_input_tokens = sum(_num(point.get("results", {}).get("total_input_tokens")) for point in points)
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
            "cache_hit_tpm": best_cache_hit_tpm,
            "cache_inclusive_tpm": best_cache_inclusive_tpm,
            "total_cached_input_tokens": total_cached_input_tokens,
            "cache_hit_rate": (
                total_cached_input_tokens / max(total_input_tokens, total_cached_input_tokens + total_cache_creation_input_tokens)
                if max(total_input_tokens, total_cached_input_tokens + total_cache_creation_input_tokens) > 0 else 0.0
            ),
            "success_rate": sum(success_rates) / len(success_rates) if success_rates else None,
            "latency_sec_p95": max(p95_values) if p95_values else None,
        }
    return summary.get("results") or {}


def _dashboard_task_item(
    task: TestTask,
    result: TestResult | None,
    progress_hub: ProgressHub,
    active_statuses: set[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, float | None], bool]:
    config = _config(task)
    expected_metrics = config.get("expected_metrics") or {}
    targets = _expected_targets(expected_metrics)
    protocol = task.api_protocol or config.get("api_protocol", "openai")
    summary_results = _summary_results(_safe_load_summary(result))
    is_active = task.status in active_statuses
    progress = progress_hub.snapshot(task.id) if is_active else None
    if progress:
        item_rpm = _num(progress.get("current_rpm"), _num(summary_results.get("rpm")))
        item_tpm = _num(progress.get("current_tpm"), _num(summary_results.get("total_tpm")))
        item_cache_hit_tpm = _num(progress.get("current_cache_hit_tpm"), _num(summary_results.get("cache_hit_tpm")))
        item_cache_inclusive_tpm = _num(progress.get("current_cache_inclusive_tpm"), _num(summary_results.get("cache_inclusive_tpm")))
        item_cached_input_tokens = _num(progress.get("current_cached_input_tokens"), _num(summary_results.get("total_cached_input_tokens")))
        item_cache_hit_rate = progress.get("current_cache_hit_rate", summary_results.get("cache_hit_rate"))
        item_attempt_rpm = _num(progress.get("attempt_rpm"), _num(summary_results.get("attempt_rpm")))
        item_attempt_tpm = _num(progress.get("attempt_tpm"), _num(summary_results.get("attempt_tpm")))
        item_success_rate = progress.get("success_rate", summary_results.get("success_rate"))
        item_p95 = progress.get("latency_sec_p95", summary_results.get("latency_sec_p95"))
        item_phase = progress.get("phase")
        item_cache_warmup_completed = progress.get("cache_warmup_completed")
        item_cache_warmup_requests = progress.get("cache_warmup_requests", config.get("cache_warmup_requests"))
    else:
        item_rpm = _num(summary_results.get("rpm"))
        item_tpm = _num(summary_results.get("total_tpm"))
        item_cache_hit_tpm = _num(summary_results.get("cache_hit_tpm"))
        item_cache_inclusive_tpm = _num(summary_results.get("cache_inclusive_tpm"))
        item_cached_input_tokens = _num(summary_results.get("total_cached_input_tokens"))
        item_cache_hit_rate = summary_results.get("cache_hit_rate")
        item_attempt_rpm = _num(summary_results.get("attempt_rpm"))
        item_attempt_tpm = _num(summary_results.get("attempt_tpm"))
        item_success_rate = summary_results.get("success_rate")
        item_p95 = summary_results.get("latency_sec_p95")
        item_phase = "completed" if task.status in {"completed", "failed", "cancelled", "interrupted"} else None
        item_cache_warmup_completed = None
        item_cache_warmup_requests = config.get("cache_warmup_requests")
    metric_item = {
        "rpm": item_rpm,
        "tpm": item_tpm,
        "cache_hit_tpm": item_cache_hit_tpm,
        "cache_inclusive_tpm": item_cache_inclusive_tpm,
        "cached_input_tokens": item_cached_input_tokens,
        "cache_hit_rate": item_cache_hit_rate,
        "attempt_rpm": item_attempt_rpm,
        "attempt_tpm": item_attempt_tpm,
        "success_rate": item_success_rate,
        "latency_p95": item_p95,
    }
    error_message = result.error_message if result else None
    task_item = {
        "id": task.id,
        "name": task.name,
        "prompt_source": config.get("prompt_source", "synthetic"),
        "custom_prompt": config.get("custom_prompt"),
        "custom_prompt_chars": config.get("custom_prompt_chars"),
        "custom_prompt_sha256": config.get("custom_prompt_sha256"),
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
        "cache_hit_tpm": item_cache_hit_tpm,
        "cache_inclusive_tpm": item_cache_inclusive_tpm,
        "cached_input_tokens": item_cached_input_tokens,
        "cache_hit_rate": item_cache_hit_rate,
        "attempt_rpm": item_attempt_rpm,
        "attempt_tpm": item_attempt_tpm,
        "success_rate": item_success_rate,
        "latency_p95": item_p95,
        "phase": item_phase,
        "cache_test_enabled": bool(config.get("cache_test_enabled", False)),
        "cache_warmup_requests": item_cache_warmup_requests,
        "cache_warmup_completed": item_cache_warmup_completed,
        "expected_metrics": expected_metrics,
        "error_message": error_message,
        "issue_tags": _task_issue_tags(task.status, metric_item, targets, error_message),
    }
    return task_item, metric_item, targets, is_active


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
    if active_tasks == 0:
        return {
            "overall_status": "idle",
            "summary": "暂无运行中任务，实时指标将在下一次压测启动后更新。",
            "reasons": [],
            "actions": [{"type": "open_report", "label": "查看最新报告"}],
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
        owner_username=task.owner_username,
        owner_role=task.owner_role,
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
        cache_test_enabled=bool(config.get("cache_test_enabled", False)),
        cache_warmup_requests=int(config.get("cache_warmup_requests") or 0),
        matrix_mode=task.matrix_mode,
        expected_metrics=config.get("expected_metrics"),
        prompt_source=config.get("prompt_source", "synthetic"),
        custom_prompt=config.get("custom_prompt"),
        custom_prompt_chars=config.get("custom_prompt_chars"),
        custom_prompt_sha256=config.get("custom_prompt_sha256"),
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


def _ensure_task_access(task: TestTask, user: AuthUser) -> None:
    if not can_access_task(user, task.owner_username):
        raise HTTPException(status_code=404, detail="任务不存在")


def _ensure_base_url_allowed(base_url: str, user: AuthUser) -> None:
    is_built_in = is_built_in_base_url(base_url)
    if user.role == "root" and not is_built_in:
        raise HTTPException(status_code=403, detail="root 模式只能使用国内或海外节点")
    if user.role == "guest" and is_built_in:
        raise HTTPException(status_code=403, detail="游客模式只能使用第三方自定义域名")


def _download_user(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> AuthUser:
    if authorization and authorization.lower().startswith("bearer "):
        user = parse_token(authorization.split(" ", 1)[1].strip())
    else:
        user = parse_token(token or "")
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


@router.post("", response_model=StartTestOut)
async def start_test(
    payload: TestCreate,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    manager: TaskManager = Depends(get_task_manager),
) -> StartTestOut:
    if user.role == "guest" and payload.prompt_source == "custom":
        raise HTTPException(status_code=403, detail="游客不能使用自定义 Case")
    _ensure_base_url_allowed(payload.base_url, user)
    try:
        task_id = await manager.start_test(payload, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to start test")
        raise HTTPException(status_code=502, detail=f"启动测试失败：{exc}") from exc

    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=500, detail="任务创建后无法读取")
    task, _ = item
    return StartTestOut(test_id=task.id, status=task.status, created_at=task.created_at)


@router.post("/custom-case-batch", response_model=CustomCaseBatchOut)
async def start_custom_case_batch(
    payload: CustomCaseBatchRequest,
    user: AuthUser = Depends(require_root),
    manager: TaskManager = Depends(get_task_manager),
) -> CustomCaseBatchOut:
    batch_id = str(uuid4())
    total = len(payload.cases) * len(payload.channels)
    test_ids: list[str] = []
    failures: list[CustomCaseBatchFailure] = []
    common = {
        "concurrency": payload.concurrency,
        "duration_sec": payload.duration_sec,
        "max_output_tokens": payload.max_output_tokens,
        "temperature": payload.temperature,
        "timeout_sec": payload.timeout_sec,
        "connect_timeout_sec": payload.connect_timeout_sec,
        "warmup_requests": payload.warmup_requests,
        "max_retries": payload.max_retries,
        "retry_backoff_base": payload.retry_backoff_base,
        "retry_backoff_max": payload.retry_backoff_max,
        "think_time_ms": payload.think_time_ms,
        "enable_stream": payload.enable_stream,
    }

    for case_index, case in enumerate(payload.cases, start=1):
        prompt = case.prompt.strip()
        for channel_index, channel in enumerate(payload.channels, start=1):
            try:
                _ensure_base_url_allowed(channel.base_url, user)
                item = TestCreate(
                    **common,
                    name=f"{payload.batch_name} / {case.name} / {channel.name}",
                    api_protocol=channel.api_protocol,
                    anthropic_version=channel.anthropic_version,
                    base_url=channel.base_url,
                    api_key=channel.api_key,
                    model=channel.model,
                    endpoint=channel.endpoint,
                    input_tokens=max(1, _estimate_prompt_tokens(prompt)),
                    matrix_mode=False,
                    input_tokens_list="",
                    concurrency_list="",
                    matrix_duration_sec=60,
                    prompt_source="custom",
                    custom_prompt=prompt,
                    expected_metrics=_custom_case_expected_metrics(
                        prompt=prompt,
                        concurrency=payload.concurrency,
                        duration_sec=payload.duration_sec,
                        max_output_tokens=payload.max_output_tokens,
                        think_time_ms=payload.think_time_ms,
                    ),
                    batch_id=batch_id,
                    batch_name=payload.batch_name,
                    batch_case_name=case.name,
                    batch_case_index=case_index,
                    batch_channel_name=channel.name,
                    batch_channel_index=channel_index,
                    batch_total_tests=total,
                )
                test_ids.append(await manager.start_test(item, user))
            except ValueError as exc:
                failures.append(CustomCaseBatchFailure(case_name=case.name, channel_name=channel.name, message=str(exc)))
            except Exception as exc:
                logger.exception("Failed to start custom case batch item")
                failures.append(CustomCaseBatchFailure(case_name=case.name, channel_name=channel.name, message=f"启动失败：{exc}"))

    if not test_ids and failures:
        raise HTTPException(status_code=400, detail="批量诊断启动失败：" + "；".join(item.message for item in failures[:3]))
    return CustomCaseBatchOut(
        batch_id=batch_id,
        batch_name=payload.batch_name,
        total=total,
        started=len(test_ids),
        test_ids=test_ids,
        failures=failures,
    )


@router.get("", response_model=TestListOut)
async def list_tests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    model: str | None = None,
    api_protocol: str | None = Query(default=None, pattern="^(openai|anthropic|gemini)$"),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    progress_hub: ProgressHub = Depends(get_progress_hub),
    manager: TaskManager = Depends(get_task_manager),
) -> TestListOut:
    manager.reconcile_active_tasks()
    total, rows = repository.list_tasks(
        page,
        page_size,
        user,
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
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    progress_hub: ProgressHub = Depends(get_progress_hub),
    manager: TaskManager = Depends(get_task_manager),
) -> dict[str, Any]:
    manager.reconcile_active_tasks()
    snapshot = repository.dashboard_snapshot(user, recent_limit=8)
    total = snapshot["total"]
    status_counts: dict[str, int] = snapshot["status_counts"]
    protocol_counts = {"openai": 0, "anthropic": 0, "gemini": 0}
    protocol_counts.update(snapshot["protocol_counts"])
    model_counts: dict[str, int] = snapshot["model_counts"]
    error_counts: dict[str, int] = snapshot["error_counts"]
    active_statuses = {"queued", "running", "stopping"}
    active_tasks = sum(status_counts.get(status, 0) for status in active_statuses)
    metric_sources: list[dict[str, Any]] = []
    target_sources: list[dict[str, float | None]] = []
    recent_tasks = []

    for task, result in snapshot["active_rows"]:
        _, metric_item, targets, is_active = _dashboard_task_item(task, result, progress_hub, active_statuses)
        if is_active:
            metric_sources.append(metric_item)
            target_sources.append(targets)

    for task, result in snapshot["recent_rows"]:
        task_item, _, _, _ = _dashboard_task_item(task, result, progress_hub, active_statuses)
        recent_tasks.append(task_item)

    sources = metric_sources
    rpm = sum(_num(item.get("rpm")) for item in sources)
    tpm = sum(_num(item.get("tpm")) for item in sources)
    cache_hit_tpm = sum(_num(item.get("cache_hit_tpm")) for item in sources)
    cache_inclusive_tpm = sum(_num(item.get("cache_inclusive_tpm")) for item in sources)
    cached_input_tokens = sum(_num(item.get("cached_input_tokens")) for item in sources)
    cache_rate_values = [
        _num(item.get("cache_hit_rate"))
        for item in sources
        if item.get("cache_hit_rate") is not None
    ]
    attempt_rpm = sum(_num(item.get("attempt_rpm")) for item in sources)
    attempt_tpm = sum(_num(item.get("attempt_tpm")) for item in sources)
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
            "cache_hit_tpm": round(cache_hit_tpm, 4),
            "cache_inclusive_tpm": round(cache_inclusive_tpm, 4),
            "cached_input_tokens": round(cached_input_tokens, 4),
            "cache_hit_rate": round(sum(cache_rate_values) / len(cache_rate_values), 4) if cache_rate_values else 0.0,
            "attempt_rpm": round(attempt_rpm, 4),
            "attempt_tpm": round(attempt_tpm, 4),
            "expected_rpm": round(expected_rpm, 4) if expected_rpm else None,
            "expected_tpm": round(expected_tpm, 4) if expected_tpm else None,
            "expected_tps": round(expected_tps, 4) if expected_tps else None,
            "expected_latency_sec": round(sum(expected_latency_values) / len(expected_latency_values), 4) if expected_latency_values else None,
            "success_rate": round(sum(success_rates) / len(success_rates), 4) if success_rates else None,
            "latency_p95": round(max(p95_values), 4) if p95_values else None,
        },
        "status_counts": status_counts,
        "protocol_counts": protocol_counts,
        "model_counts": model_counts,
        "error_counts": error_counts,
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


@router.post("/bulk-delete", response_model=BulkDeleteOut)
async def bulk_delete_tests(
    payload: BulkDeleteIn,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> BulkDeleteOut:
    ids = list(dict.fromkeys(task_id.strip() for task_id in payload.ids if task_id and task_id.strip()))
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的记录")

    deleted = 0
    not_found: list[str] = []
    for task_id in ids:
        if repository.delete_task(task_id, user):
            deleted += 1
        else:
            not_found.append(task_id)

    return BulkDeleteOut(requested=len(ids), deleted=deleted, not_found=not_found)


@router.get("/{task_id}", response_model=TestTaskOut)
async def get_test(
    task_id: str,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    progress_hub: ProgressHub = Depends(get_progress_hub),
    manager: TaskManager = Depends(get_task_manager),
) -> TestTaskOut:
    manager.reconcile_active_tasks()
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    return _task_out(task, result, progress_hub.snapshot(task_id))


@router.post("/{task_id}/stop")
async def stop_test(
    task_id: str,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    manager: TaskManager = Depends(get_task_manager),
) -> dict[str, Any]:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在或不在运行中")
    _ensure_task_access(item[0], user)
    stopped = await manager.stop_test(task_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="任务不存在或不在运行中")
    return {"test_id": task_id, "status": "stopping"}


@router.post("/{task_id}/resume-matrix", response_model=StartTestOut)
async def resume_matrix_test(
    task_id: str,
    payload: MatrixResumeRequest,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
    manager: TaskManager = Depends(get_task_manager),
) -> StartTestOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    if not task.matrix_mode:
        raise HTTPException(status_code=400, detail="非矩阵任务不能续跑")
    _ensure_base_url_allowed(task.base_url, user)
    if task.status not in {"completed", "failed", "cancelled", "interrupted"}:
        raise HTTPException(status_code=400, detail="当前任务状态不能续跑")
    existing_matrix_results = _matrix_results_for_resume(result)
    if not existing_matrix_results:
        raise HTTPException(status_code=400, detail="未找到可续跑的矩阵结果")

    try:
        new_task_id = await manager.resume_matrix_test(
            task_id,
            _config(task),
            payload.api_key,
            existing_matrix_results,
            user,
            resume_policy=payload.resume_policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to resume matrix test")
        raise HTTPException(status_code=502, detail=f"续跑矩阵失败：{exc}") from exc

    new_item = repository.get_task(new_task_id)
    if not new_item:
        raise HTTPException(status_code=500, detail="续跑任务创建后无法读取")
    new_task, _ = new_item
    repository.add_event(new_task_id, "info", f"基于任务 {task_id} 续跑矩阵")
    return StartTestOut(test_id=new_task.id, status=new_task.status, created_at=new_task.created_at)


@router.delete("/{task_id}")
async def delete_test(
    task_id: str,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    deleted = repository.delete_task(task_id, user)
    if not deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"deleted": True}


@router.get("/{task_id}/report", response_model=ReportOut)
async def get_report(
    task_id: str,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> ReportOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    config = json.loads(task.config_json)
    summary = _summary(result)
    charts = build_chart_data(
        summary,
        result.details_jsonl_path if result else None,
        charts_path=result.charts_path if result else None,
    )
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
        task_status=task.status,
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
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> DetailsOut:
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    total, items = load_details(
        result.details_jsonl_path if result else None,
        page=page,
        page_size=page_size,
        total_count=result.detail_count if result else None,
    )
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
    user: AuthUser = Depends(_download_user),
    repository: Repository = Depends(get_repository),
) -> FileResponse:
    if kind not in {"summary", "details", "markdown", "html", "matrix_csv"}:
        raise HTTPException(status_code=404, detail="不支持的下载类型")
    item = repository.get_task(task_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    task, result = item
    _ensure_task_access(task, user)
    path = _safe_download_file(_download_path(result, kind))
    if not path:
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(path)
