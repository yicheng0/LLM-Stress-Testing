from __future__ import annotations

import asyncio
import html
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp

from backend.app.core.repository import _redact_sensitive, _redact_text
from loadtest.models import TokenUsage
from loadtest.prompt import PromptFactory, TokenEstimator
from loadtest.protocols import (
    build_headers,
    build_messages_payload,
    build_url,
    extract_protocol_error,
    extract_response_text,
    extract_token_usage,
)
from loadtest.streaming import SseStreamParser


CACHE_PREFIX_TARGET_TOKENS = 4096
CACHE_CASES = {
    "repeat": {
        "name": "缓存命中-重复请求",
        "description": "准备请求与验证请求完全相同。",
    },
    "multiturn": {
        "name": "缓存命中-多轮对话",
        "description": "验证请求保留首轮上下文并新增一轮消息。",
    },
    "variable_suffix": {
        "name": "缓存命中-尾部变化",
        "description": "两次请求保持公共前缀不变，仅改变尾部内容。",
    },
}

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
LogCallback = Callable[[str, str], Awaitable[None] | None]


@dataclass(frozen=True)
class CacheCaseDefinition:
    case_id: str
    case_name: str
    description: str
    prepare_messages: list[dict[str, str]]
    validate_messages: list[dict[str, str]]


def build_cache_prefix(model: str, target_tokens: int = CACHE_PREFIX_TARGET_TOKENS) -> tuple[str, int]:
    estimator = TokenEstimator(model)
    prefix = PromptFactory(estimator).build_prompt(target_tokens)
    return prefix, estimator.count(prefix)


def build_cache_case(case_id: str, prefix: str) -> CacheCaseDefinition:
    metadata = CACHE_CASES[case_id]
    if case_id == "repeat":
        messages = [{"role": "user", "content": f"{prefix}\n\n缓存诊断：请只回答 OK。"}]
        prepare = messages
        validate = [dict(item) for item in messages]
    elif case_id == "multiturn":
        first = {"role": "user", "content": f"{prefix}\n\n第一轮：请只回答 OK。"}
        prepare = [first]
        validate = [
            dict(first),
            {"role": "assistant", "content": "OK"},
            {"role": "user", "content": "第二轮：请继续只回答 OK。"},
        ]
    else:
        prepare = [{"role": "user", "content": f"{prefix}\n\n尾部版本 A：请只回答 A。"}]
        validate = [{"role": "user", "content": f"{prefix}\n\n尾部版本 B：请只回答 B。"}]
    return CacheCaseDefinition(
        case_id=case_id,
        case_name=metadata["name"],
        description=metadata["description"],
        prepare_messages=prepare,
        validate_messages=validate,
    )


def classify_cache_case(prepare: dict[str, Any], validate: dict[str, Any] | None) -> tuple[str, str | None]:
    if not prepare.get("ok"):
        return "failed", "prepare"
    if not validate or not validate.get("ok"):
        return "failed", "validate"
    cache = validate.get("cache") or {}
    if not cache.get("observed"):
        return "unverifiable", None
    if int(cache.get("cached_input_tokens") or 0) > 0:
        return "cache_hit", None
    return "cache_miss", None


def classify_cache_request(phase: str, evidence: dict[str, Any]) -> str | None:
    """Return the approved per-validation cache classification.

    Cache establishment is deliberately excluded from cache hit accounting,
    even if an upstream happens to report cache usage for that request.
    """
    if phase == "prepare":
        return None
    if not evidence.get("ok"):
        return "failed"
    cache = evidence.get("cache") or {}
    if not cache.get("observed"):
        return "unverifiable"
    if int(cache.get("cached_input_tokens") or 0) > 0:
        return "cache_hit"
    return "cache_miss"


def cache_case_requests(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Read new request evidence or project a legacy prepare/validate case.

    This is intentionally a read-only projection: callers must not write the
    returned legacy data back to stored summaries.
    """
    requests = case.get("requests")
    if isinstance(requests, list):
        return requests

    projected: list[dict[str, Any]] = []
    for request_index, phase in enumerate(("prepare", "validate"), start=1):
        source = case.get(phase)
        if not isinstance(source, dict):
            continue
        item = dict(source)
        item.setdefault("case_id", case.get("case_id"))
        item.setdefault("request_index", request_index)
        item.setdefault("phase", phase)
        item.setdefault("phase_label", "缓存建立" if phase == "prepare" else "缓存验证")
        if "classification" not in item:
            item["classification"] = classify_cache_request(phase, item)
        projected.append(item)
    return projected


def _request_counts(requests: list[dict[str, Any]]) -> dict[str, Any]:
    validation = [item for item in requests if item.get("phase") != "prepare"]
    cache_hits = sum(item.get("classification") == "cache_hit" for item in validation)
    cache_misses = sum(item.get("classification") == "cache_miss" for item in validation)
    unverifiable = sum(item.get("classification") == "unverifiable" for item in validation)
    failed = sum(item.get("classification") == "failed" for item in validation)
    decidable = cache_hits + cache_misses
    return {
        "validation_requests": len(validation),
        "cache_hit_requests": cache_hits,
        "cache_miss_requests": cache_misses,
        "unverifiable_requests": unverifiable,
        "failed_requests": failed,
        "decidable_requests": decidable,
        "cache_hit_rate": round(cache_hits / decidable, 4) if decidable else None,
    }


def cache_case_statistics(case: dict[str, Any]) -> dict[str, Any]:
    """Return request-level counts for either a current or legacy Case."""
    requests = cache_case_requests(case)
    return {"executed_requests": len(requests), **_request_counts(requests)}


def summarize_cache_case(
    case_id: str,
    definition: CacheCaseDefinition,
    requests: list[dict[str, Any]],
    planned_requests: int,
) -> dict[str, Any]:
    """Create one Case's aggregate without retaining request bodies or replies."""
    counts = _request_counts(requests)
    prepare = next((item for item in requests if item.get("phase") == "prepare"), None)
    validations = [item for item in requests if item.get("phase") != "prepare"]
    successful_validations = [item for item in validations if item.get("ok")]
    if not prepare or not prepare.get("ok"):
        status, failure_phase = "failed", "prepare"
        error_source = prepare or {}
    elif not successful_validations:
        status, failure_phase = "failed", "validate"
        error_source = next((item for item in reversed(validations) if not item.get("ok")), {})
    elif not counts["decidable_requests"]:
        status, failure_phase = "unverifiable", None
        error_source = {}
    elif counts["cache_hit_requests"]:
        status, failure_phase = "cache_hit", None
        error_source = {}
    else:
        status, failure_phase = "cache_miss", None
        error_source = {}
    return {
        "case_id": case_id,
        "case_name": definition.case_name,
        "description": definition.description,
        "planned_requests": planned_requests,
        "executed_requests": len(requests),
        **counts,
        "status": status,
        "failure_phase": failure_phase,
        "error_type": error_source.get("error_type"),
        "error_message": error_source.get("error_message"),
        "requests": requests,
        # Keep the historical shape available to existing report/read callers.
        "prepare": prepare,
        "validate": next((item for item in validations), None),
    }


def redact_cache_text(value: str, api_key: str | None) -> str:
    redacted = value or ""
    if api_key:
        redacted = redacted.replace(api_key, "[REDACTED]")
    return _redact_text(redacted)


def _cache_hit_rate(input_tokens: int, usage: TokenUsage) -> float | None:
    denominator = max(input_tokens, usage.cached_input_tokens + usage.cache_creation_input_tokens)
    if denominator <= 0:
        return None
    return round(usage.cached_input_tokens / denominator, 4)


def _request_evidence(
    *,
    case_id: str,
    phase: str,
    ok: bool,
    status: int,
    latency_sec: float,
    ttft_sec: float | None,
    input_tokens: int,
    usage: TokenUsage | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    request_index: int | None = None,
) -> dict[str, Any]:
    usage = usage or TokenUsage()
    actual_input_tokens = usage.input_tokens if usage.input_tokens > 0 else input_tokens
    total_tokens = usage.total_tokens or (actual_input_tokens + usage.output_tokens if ok else actual_input_tokens)
    cache_total = usage.cache_inclusive_total_tokens or total_tokens
    evidence = {
        "case_id": case_id,
        "phase": phase,
        "ok": ok,
        "status": status,
        "latency_sec": round(latency_sec, 6),
        "ttft_sec": None if ttft_sec is None else round(ttft_sec, 6),
        "input_tokens": actual_input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": total_tokens,
        "cache": {
            "observed": usage.cache_usage_observed,
            "cached_input_tokens": usage.cached_input_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_inclusive_total_tokens": cache_total,
            "cache_hit_rate": _cache_hit_rate(actual_input_tokens, usage),
        },
        "error_type": error_type,
        "error_message": error_message or None,
    }
    if request_index is not None:
        evidence["request_index"] = request_index
        evidence["phase_label"] = "缓存建立" if phase == "prepare" else "缓存验证"
        evidence["classification"] = classify_cache_request(phase, evidence)
    return evidence


class CacheDiagnosticsRunner:
    def __init__(
        self,
        config: dict[str, Any],
        output_dir: Path,
        *,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self.config = config
        self.output_dir = output_dir
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_event = stop_event
        self.estimator = TokenEstimator(str(config.get("model") or "gpt-5.5"))
        self.prefix_target_tokens = int(config.get("input_tokens") or CACHE_PREFIX_TARGET_TOKENS)
        self.requests_per_case = int(config.get("requests_per_case") or 10)
        self.prefix, self.prefix_tokens = build_cache_prefix(
            str(config.get("model") or "gpt-5.5"), self.prefix_target_tokens,
        )
        self.parser = SseStreamParser()
        self.case_results: list[dict[str, Any]] = []
        self.request_evidence: list[dict[str, Any]] = []

    def _safe_error(
        self,
        value: str | None,
        messages: list[dict[str, str]] | None = None,
    ) -> str | None:
        redacted = (value or "").replace(self.prefix, "[CACHE_PREFIX_REDACTED]")
        for message in messages or []:
            content = str(message.get("content") or "")
            if not content:
                continue
            redacted = redacted.replace(content, "[REQUEST_CONTENT_REDACTED]")
            escaped = json.dumps(content, ensure_ascii=False)[1:-1]
            redacted = redacted.replace(escaped, "[REQUEST_CONTENT_REDACTED]")
        redacted = redact_cache_text(redacted, str(self.config.get("api_key") or ""))
        return redacted or None

    async def _wait_before_retry(self, delay: float) -> bool:
        if self.should_stop():
            return False
        if not self.stop_event:
            await asyncio.sleep(delay)
            return True
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
            return False
        except asyncio.TimeoutError:
            return not self.should_stop()

    async def _maybe_await(self, value: Any) -> None:
        if asyncio.iscoroutine(value):
            await value

    async def emit_progress(
        self,
        *,
        current_case: str | None = None,
        current_case_id: str | None = None,
        current_request_index: int | None = None,
    ) -> None:
        if not self.progress_callback:
            return
        counts = self._counts()
        await self._maybe_await(self.progress_callback({
            "task_kind": "cache_diagnostics",
            "phase": "cache_diagnostics",
            "current_case": current_case,
            "current_case_id": current_case_id,
            "current_request_index": current_request_index,
            "requests_per_case": self.requests_per_case,
            "completed_cases": len(self.case_results),
            "total_cases": len(self.config.get("case_ids") or []),
            **counts,
        }))

    async def emit_log(self, level: str, message: str) -> None:
        if self.log_callback:
            await self._maybe_await(self.log_callback(level, message))

    def should_stop(self) -> bool:
        return bool(self.stop_event and self.stop_event.is_set())

    def _counts(self) -> dict[str, Any]:
        request_counts = _request_counts(self.request_evidence)
        return {
            "cache_hit_cases": sum(item["status"] == "cache_hit" for item in self.case_results),
            "cache_miss_cases": sum(item["status"] == "cache_miss" for item in self.case_results),
            "unverifiable_cases": sum(item["status"] == "unverifiable" for item in self.case_results),
            "failed_cases": sum(item["status"] == "failed" for item in self.case_results),
            "planned_requests": len(self.config.get("case_ids") or []) * self.requests_per_case,
            "executed_requests": len(self.request_evidence),
            **request_counts,
        }

    def _finalize_evidence(self, evidence: dict[str, Any], request_index: int) -> dict[str, Any]:
        """Attach persisted request-sequence metadata after a transport attempt."""
        evidence.pop("_response_text", None)
        evidence["request_index"] = request_index
        evidence["phase_label"] = "缓存建立" if evidence.get("phase") == "prepare" else "缓存验证"
        evidence["classification"] = classify_cache_request(str(evidence.get("phase") or ""), evidence)
        return evidence

    def _input_tokens(self, messages: list[dict[str, str]]) -> int:
        return self.estimator.count("\n".join(str(item.get("content") or "") for item in messages))

    async def _send_request(
        self,
        session: aiohttp.ClientSession,
        case_id: str,
        phase: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        input_tokens = self._input_tokens(messages)
        protocol = str(self.config.get("api_protocol") or "openai")
        endpoint = str(self.config.get("endpoint") or "/v1/chat/completions")
        url = build_url(
            str(self.config["base_url"]), endpoint, protocol,
            model=str(self.config.get("model") or ""),
            enable_stream=bool(self.config.get("enable_stream", True)),
        )
        headers = build_headers(
            protocol,
            api_key=str(self.config.get("api_key") or ""),
            anthropic_version=str(self.config.get("anthropic_version") or "2023-06-01"),
        )
        payload = build_messages_payload(
            protocol,
            endpoint=endpoint,
            model=str(self.config.get("model") or ""),
            messages=messages,
            max_output_tokens=int(self.config.get("max_output_tokens") or 128),
            temperature=self.config.get("temperature"),
            enable_stream=bool(self.config.get("enable_stream", True)),
            cache_prefix=self.prefix,
        )
        started_perf = time.perf_counter()
        attempts = int(self.config.get("max_retries") or 0) + 1
        for attempt in range(1, attempts + 1):
            if self.should_stop():
                return None
            try:
                async with session.post(url, headers=headers, json=payload) as response:
                    if 200 <= response.status < 300:
                        if self.config.get("enable_stream", True):
                            ttft, usage, protocol_error, response_text, observed_event = await self.parser.parse_stream_evidence(response.content, started_perf)
                            if protocol_error:
                                return _request_evidence(
                                    case_id=case_id, phase=phase, ok=False, status=response.status,
                                    latency_sec=time.perf_counter() - started_perf, ttft_sec=ttft,
                                    input_tokens=input_tokens, error_type="PROTOCOL_ERROR", error_message=self._safe_error(protocol_error, messages),
                                )
                            if not observed_event or (not response_text and usage.output_tokens <= 0):
                                return _request_evidence(
                                    case_id=case_id, phase=phase, ok=False, status=response.status,
                                    latency_sec=time.perf_counter() - started_perf, ttft_sec=ttft,
                                    input_tokens=input_tokens, error_type="PROTOCOL_ERROR",
                                    error_message="流式响应未包含可识别的模型输出",
                                )
                            if case_id == "multiturn" and not response_text:
                                return _request_evidence(
                                    case_id=case_id, phase=phase, ok=False, status=response.status,
                                    latency_sec=time.perf_counter() - started_perf, ttft_sec=ttft,
                                    input_tokens=input_tokens, error_type="PROTOCOL_ERROR",
                                    error_message="多轮请求未采集到可复用的模型回复",
                                )
                            evidence = _request_evidence(
                                case_id=case_id, phase=phase, ok=True, status=response.status,
                                latency_sec=time.perf_counter() - started_perf, ttft_sec=ttft,
                                input_tokens=input_tokens, usage=usage,
                            )
                            evidence["_response_text"] = response_text
                            return evidence
                        text = await response.text()
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError:
                            data = {}
                        protocol_error = extract_protocol_error(data)
                        if protocol_error:
                            return _request_evidence(
                                case_id=case_id, phase=phase, ok=False, status=response.status,
                                latency_sec=time.perf_counter() - started_perf, ttft_sec=None,
                                input_tokens=input_tokens, error_type="PROTOCOL_ERROR", error_message=self._safe_error(protocol_error, messages),
                            )
                        raw_usage = data.get("usage") or data.get("usageMetadata") or {}
                        usage = extract_token_usage(raw_usage if isinstance(raw_usage, dict) else {})
                        response_text = extract_response_text(data)
                        if not response_text and usage.output_tokens <= 0:
                            return _request_evidence(
                                case_id=case_id, phase=phase, ok=False, status=response.status,
                                latency_sec=time.perf_counter() - started_perf, ttft_sec=None,
                                input_tokens=input_tokens, error_type="PROTOCOL_ERROR",
                                error_message="响应未包含可识别的模型输出",
                            )
                        if case_id == "multiturn" and not response_text:
                            return _request_evidence(
                                case_id=case_id, phase=phase, ok=False, status=response.status,
                                latency_sec=time.perf_counter() - started_perf, ttft_sec=None,
                                input_tokens=input_tokens, error_type="PROTOCOL_ERROR",
                                error_message="多轮请求未采集到可复用的模型回复",
                            )
                        evidence = _request_evidence(
                            case_id=case_id, phase=phase, ok=True, status=response.status,
                            latency_sec=time.perf_counter() - started_perf, ttft_sec=None,
                            input_tokens=input_tokens, usage=usage,
                        )
                        evidence["_response_text"] = response_text
                        return evidence
                    body = await response.text()
                    retryable = response.status in {408, 409, 429, 500, 502, 503, 504}
                    if retryable and attempt < attempts and not self.should_stop():
                        delay = min(
                            float(self.config.get("retry_backoff_max") or 8),
                            float(self.config.get("retry_backoff_base") or 1) * (2 ** (attempt - 1)),
                        )
                        if not await self._wait_before_retry(delay):
                            return None
                        continue
                    return _request_evidence(
                        case_id=case_id, phase=phase, ok=False, status=response.status,
                        latency_sec=time.perf_counter() - started_perf, ttft_sec=None,
                        input_tokens=input_tokens, error_type=f"HTTP_{response.status}",
                        error_message=f"上游返回 HTTP {response.status}",
                    )
            except asyncio.TimeoutError as exc:
                if attempt < attempts and not self.should_stop():
                    continue
                return _request_evidence(
                    case_id=case_id, phase=phase, ok=False, status=0,
                    latency_sec=time.perf_counter() - started_perf, ttft_sec=None,
                    input_tokens=input_tokens, error_type="TIMEOUT", error_message=self._safe_error(str(exc), messages),
                )
            except aiohttp.ClientError as exc:
                if attempt < attempts and not self.should_stop():
                    continue
                return _request_evidence(
                    case_id=case_id, phase=phase, ok=False, status=0,
                    latency_sec=time.perf_counter() - started_perf, ttft_sec=None,
                    input_tokens=input_tokens, error_type="CLIENT_ERROR", error_message=self._safe_error(str(exc), messages),
                )
        raise RuntimeError("缓存专项请求未产生结果")

    async def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timeout = aiohttp.ClientTimeout(
            total=int(self.config.get("timeout_sec") or 600),
            sock_connect=int(self.config.get("connect_timeout_sec") or 30),
        )
        connector = aiohttp.TCPConnector(ssl=False)
        await self.emit_progress()
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            for case_id in self.config.get("case_ids") or []:
                if self.should_stop():
                    break
                definition = build_cache_case(case_id, self.prefix)
                await self.emit_log("info", f"开始 {definition.case_name}")
                case_requests: list[dict[str, Any]] = []
                multiturn_context = [dict(item) for item in definition.prepare_messages]
                stopped = False
                for request_index in range(1, self.requests_per_case + 1):
                    if self.should_stop():
                        stopped = True
                        break
                    phase = "prepare" if request_index == 1 else "validate"
                    if case_id == "repeat":
                        messages = [dict(item) for item in definition.prepare_messages]
                    elif case_id == "variable_suffix":
                        source = definition.prepare_messages if phase == "prepare" else definition.validate_messages
                        messages = [dict(item) for item in source]
                    else:
                        if phase == "prepare":
                            messages = [dict(item) for item in multiturn_context]
                        else:
                            next_turn = sum(item.get("role") == "assistant" for item in multiturn_context) + 1
                            messages = [
                                *[dict(item) for item in multiturn_context],
                                {"role": "user", "content": f"第{next_turn}轮：请继续只回答 OK。"},
                            ]
                    await self.emit_progress(
                        current_case=definition.case_name,
                        current_case_id=case_id,
                        current_request_index=request_index,
                    )
                    evidence = await self._send_request(session, case_id, phase, messages)
                    if evidence is None:
                        stopped = True
                        break
                    response_text = str(evidence.get("_response_text") or "")
                    evidence = self._finalize_evidence(evidence, request_index)
                    case_requests.append(evidence)
                    self.request_evidence.append(evidence)
                    if case_id == "multiturn" and evidence.get("ok") and response_text:
                        multiturn_context = [*messages, {"role": "assistant", "content": response_text}]
                    await self.emit_progress(
                        current_case=definition.case_name,
                        current_case_id=case_id,
                        current_request_index=request_index,
                    )
                    # A failed establishment cannot be followed by a validation.
                    if phase == "prepare" and not evidence.get("ok"):
                        break

                if case_requests:
                    case_result = summarize_cache_case(
                        case_id, definition, case_requests, self.requests_per_case,
                    )
                    self.case_results.append(case_result)
                    await self.emit_log("info", f"{definition.case_name} 完成：{case_result['status']}")
                    await self.emit_progress(
                        current_case=definition.case_name,
                        current_case_id=case_id,
                        current_request_index=len(case_requests),
                    )
                if stopped or self.should_stop():
                    break

        summary = self._summary()
        files = self._write_files(summary)
        await self.emit_progress()
        return {"summary": summary, "files": files}

    def _summary(self) -> dict[str, Any]:
        safe_config = _redact_sensitive(dict(self.config))
        safe_config.update({
            "task_kind": "cache_diagnostics",
            "cache_prefix_target_tokens": self.prefix_target_tokens,
            "cache_prefix_actual_tokens": self.prefix_tokens,
            "requests_per_case": self.requests_per_case,
        })
        counts = self._counts()
        return {
            "task_kind": "cache_diagnostics",
            "config": safe_config,
            "results": {
                "total_cases": len(self.case_results),
                "executed_requests": len(self.request_evidence),
                **counts,
            },
            "cases": self.case_results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _write_files(self, summary: dict[str, Any]) -> dict[str, Any]:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.output_dir / f"summary_{timestamp}.json"
        details_path = self.output_dir / f"details_{timestamp}.jsonl"
        report_path = self.output_dir / f"report_{timestamp}.md"
        html_path = self.output_dir / f"report_{timestamp}.html"
        charts_path = self.output_dir / f"charts_{timestamp}.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        with details_path.open("w", encoding="utf-8") as detail_file:
            for item in self.request_evidence:
                detail_file.write(json.dumps(item, ensure_ascii=False) + "\n")
        charts_path.write_text("{}\n", encoding="utf-8")
        report_path.write_text(render_cache_markdown(summary), encoding="utf-8")
        html_path.write_text(render_cache_html(summary), encoding="utf-8")
        return {
            "summary_path": str(summary_path),
            "details_jsonl_path": str(details_path),
            "report_md_path": str(report_path),
            "report_html_path": str(html_path),
            "matrix_csv_path": None,
            "charts_path": str(charts_path),
            "detail_count": len(self.request_evidence),
        }


def render_cache_markdown(summary: dict[str, Any]) -> str:
    config = summary.get("config") or {}
    results = summary.get("results") or {}
    hit_rate = results.get("cache_hit_rate")
    display_rate = "不可用" if hit_rate is None else f"{float(hit_rate):.2%}"
    lines = [
        "# 缓存专项测试报告",
        "",
        f"- 公共前缀目标 Token: {config.get('cache_prefix_target_tokens', '不可用')}",
        f"- 公共前缀实际 Token: {config.get('cache_prefix_actual_tokens', '不可用')}",
        f"- 每个 Case 请求次数: {config.get('requests_per_case', '不可用')}",
        f"- 计划请求数: {results.get('planned_requests', '不可用')}",
        f"- 实际请求数: {results.get('executed_requests', 0)}",
        f"- 可判定验证数: {results.get('decidable_requests', '不可用')}",
        f"- 验证命中/未命中/无法判定/失败: {results.get('cache_hit_requests', '不可用')}/"
        f"{results.get('cache_miss_requests', '不可用')}/{results.get('unverifiable_requests', '不可用')}/"
        f"{results.get('failed_requests', '不可用')}",
        f"- 总体缓存命中率: {display_rate}",
        f"- Case 总数: {results.get('total_cases', 0)}",
        f"- 缓存命中: {results.get('cache_hit_cases', 0)}",
        f"- 未命中缓存: {results.get('cache_miss_cases', 0)}",
        f"- 无法判定: {results.get('unverifiable_cases', 0)}",
        f"- 执行失败: {results.get('failed_cases', 0)}",
        "",
    ]
    for case in summary.get("cases") or []:
        statistics = cache_case_statistics(case)
        rate = case["cache_hit_rate"] if "cache_hit_rate" in case else statistics["cache_hit_rate"]
        lines.extend([
            f"## {case.get('case_name')}", "",
            f"- 判定: {case.get('status')}",
            f"- 请求: {case.get('executed_requests', statistics['executed_requests'])}/{case.get('planned_requests', '不可用')}",
            f"- 验证样本: {case.get('validation_requests', statistics['validation_requests'])}；命中/未命中/无法判定/失败: "
            f"{case.get('cache_hit_requests', statistics['cache_hit_requests'])}/{case.get('cache_miss_requests', statistics['cache_miss_requests'])}/"
            f"{case.get('unverifiable_requests', statistics['unverifiable_requests'])}/{case.get('failed_requests', statistics['failed_requests'])}",
            f"- Case 命中率: {'不可用' if rate is None else f'{float(rate):.2%}'}", "",
            "| 序号 | 阶段 | 判定 | 状态码 | 延迟 | TTFT | 输入 | 输出 | 总 Token | 缓存命中 | 缓存创建 | 含缓存 | 请求缓存比例 | 错误 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ])
        for item in cache_case_requests(case):
            cache = item.get("cache") or {}
            cache_observed = bool(cache.get("observed"))
            lines.append(
                f"| {item.get('request_index', '-')} | {item.get('phase_label') or item.get('phase') or '-'} | "
                f"{item.get('classification') or '-'} | {item.get('status', '-')} | {item.get('latency_sec', '-')} | "
                f"{item.get('ttft_sec') if item.get('ttft_sec') is not None else '不可用'} | {item.get('input_tokens', '-')} | "
                f"{item.get('output_tokens', '-')} | {item.get('total_tokens', '-')} | "
                f"{cache.get('cached_input_tokens', 0) if cache_observed else '不可用'} | "
                f"{cache.get('cache_creation_input_tokens', 0) if cache_observed else '不可用'} | "
                f"{cache.get('cache_inclusive_total_tokens', '不可用')} | "
                f"{cache.get('cache_hit_rate', '不可用') if cache_observed else '不可用'} | "
                f"{' '.join(str(value) for value in (item.get('error_type'), item.get('error_message')) if value) or '-'} |"
            )
        lines.append("")
    return "\n".join(lines)


def render_cache_html(summary: dict[str, Any]) -> str:
    config = summary.get("config") or {}
    results = summary.get("results") or {}
    rows = []
    for case in summary.get("cases") or []:
        rate = case.get("cache_hit_rate")
        rows.append(
            f"<tr><td>{html.escape(str(case.get('case_name') or ''))}</td>"
            f"<td>{html.escape(str(case.get('status') or ''))}</td>"
            f"<td>{html.escape(str(case.get('executed_requests', len(cache_case_requests(case)))))}/"
            f"{html.escape(str(case.get('planned_requests') or '-'))}</td>"
            f"<td>{html.escape('不可用' if rate is None else f'{float(rate):.2%}')}</td>"
            f"<td>{html.escape(str(case.get('failure_phase') or '-'))}</td></tr>"
        )
    evidence_sections = []
    for case in summary.get("cases") or []:
        request_rows = []
        for item in cache_case_requests(case):
            cache = item.get("cache") or {}
            cache_observed = bool(cache.get("observed"))
            request_rows.append(
                "<tr>"
                f"<td>{html.escape(str(item.get('request_index') or '-'))}</td>"
                f"<td>{html.escape(str(item.get('phase_label') or item.get('phase') or '-'))}</td>"
                f"<td>{html.escape(str(item.get('classification') or '-'))}</td>"
                f"<td>{html.escape(str(item.get('status') or '-'))}</td>"
                f"<td>{html.escape(str(item.get('latency_sec') or '-'))}</td>"
                f"<td>{html.escape('不可用' if item.get('ttft_sec') is None else str(item.get('ttft_sec')))}</td>"
                f"<td>{html.escape(str(item.get('input_tokens') or '-'))}</td>"
                f"<td>{html.escape(str(item.get('output_tokens') or '-'))}</td>"
                f"<td>{html.escape(str(item.get('total_tokens') or '-'))}</td>"
                f"<td>{html.escape(str(cache.get('cached_input_tokens', 0) if cache_observed else '不可用'))}</td>"
                f"<td>{html.escape(str(cache.get('cache_creation_input_tokens', 0) if cache_observed else '不可用'))}</td>"
                f"<td>{html.escape(str(cache.get('cache_inclusive_total_tokens', '不可用')))}</td>"
                f"<td>{html.escape(str(cache.get('cache_hit_rate', '不可用') if cache_observed else '不可用'))}</td>"
                f"<td>{html.escape(' '.join(str(value) for value in (item.get('error_type'), item.get('error_message')) if value) or '-')}</td>"
                "</tr>"
            )
        evidence_sections.append(
            f"<h2>{html.escape(str(case.get('case_name') or '缓存 Case'))}</h2>"
            "<table border='1'><thead><tr><th>序号</th><th>阶段</th><th>判定</th><th>状态码</th>"
            "<th>延迟</th><th>TTFT</th><th>输入</th><th>输出</th><th>总 Token</th>"
            "<th>缓存命中</th><th>缓存创建</th><th>含缓存</th><th>请求缓存比例</th><th>错误</th></tr></thead><tbody>"
            + "".join(request_rows) + "</tbody></table>"
        )
    rate = results.get("cache_hit_rate")
    return (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>缓存专项测试报告</title>"
        "<body><h1>缓存专项测试报告</h1>"
        f"<p>公共前缀目标 Token：{html.escape(str(config.get('cache_prefix_target_tokens', '不可用')))}；"
        f"公共前缀实际 Token：{html.escape(str(config.get('cache_prefix_actual_tokens', '不可用')))}；"
        f"每个 Case 请求次数：{html.escape(str(config.get('requests_per_case', '不可用')))}；"
        f"计划/实际请求：{html.escape(str(results.get('planned_requests', '不可用')))}/{html.escape(str(results.get('executed_requests', 0)))}；"
        f"可判定验证：{html.escape(str(results.get('decidable_requests', '不可用')))}；"
        f"命中/未命中/无法判定/失败：{html.escape(str(results.get('cache_hit_requests', '不可用')))}/"
        f"{html.escape(str(results.get('cache_miss_requests', '不可用')))}/"
        f"{html.escape(str(results.get('unverifiable_requests', '不可用')))}/"
        f"{html.escape(str(results.get('failed_requests', '不可用')))}；"
        f"总体缓存命中率：{html.escape('不可用' if rate is None else f'{float(rate):.2%}')}</p>"
        "<table border='1'><thead><tr><th>Case</th><th>判定</th><th>实际/计划</th><th>命中率</th><th>失败阶段</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>" + "".join(evidence_sections) + "</body></html>"
    )
