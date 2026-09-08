from __future__ import annotations

import asyncio
import hashlib
import html
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp

from loadtest.protocols import build_headers, build_payload, build_url, extract_token_usage
from loadtest.prompt import TokenEstimator, PromptFactory
from loadtest.streaming import SseStreamParser

PRICE_QUANTUM = Decimal("0.00000001")
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
LogCallback = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class UsageEvidence:
    usage_present: bool
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    cache_creation_input_tokens: int | None
    latency_sec: float | None
    ttft_sec: float | None
    http_status: int | None
    ok: bool
    error_type: str | None = None
    error_message: str | None = None
    raw_usage: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "usage_present": self.usage_present,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "latency_sec": round(self.latency_sec, 6) if self.latency_sec is not None else None,
            "ttft_sec": round(self.ttft_sec, 6) if self.ttft_sec is not None else None,
            "http_status": self.http_status,
            "ok": self.ok,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "raw_usage": redact_sensitive(self.raw_usage or {}),
        }


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if (
                "api_key" in lowered
                or lowered in {"authorization", "x_api_key", "x_goog_api_key", "access_token", "password", "secret"}
                or lowered.endswith("_secret")
            ):
                continue
            if lowered in {"prompt", "messages", "input", "contents", "content", "output", "response", "request", "request_body"}:
                out[key] = "[REDACTED]"
                continue
            out[key] = redact_sensitive(item)
        return out
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return value[:300]
    return value


def redact_credentials_text(value: Any, *secrets: str | None) -> str:
    text = str(value or "")
    for secret in secrets:
        candidate = str(secret or "")
        if candidate:
            text = text.replace(candidate, "[REDACTED]")
    return redact_sensitive(text)


def _parse_usage_evidence(raw_usage: dict[str, Any], protocol: str) -> tuple[bool, int | None, int | None, int | None, int | None, int | None]:
    """Parse only fields that the response actually supplied; never turn missing usage into zero."""
    if not isinstance(raw_usage, dict):
        return False, None, None, None, None, None
    if protocol == "gemini":
        input_key, output_key, total_key = "promptTokenCount", "candidatesTokenCount", "totalTokenCount"
        cache_key, write_key = "cachedContentTokenCount", None
    else:
        input_key = "input_tokens" if protocol == "anthropic" else "prompt_tokens"
        output_key = "output_tokens" if protocol == "anthropic" else "completion_tokens"
        total_key = "total_tokens"
        cache_key, write_key = "cache_read_input_tokens", "cache_creation_input_tokens"
    def read_int(key: str | None, aliases: tuple[str, ...] = ()) -> int | None:
        if not key:
            return None
        candidates: list[tuple[str, Any]] = []
        for candidate in (key, *aliases):
            if candidate in raw_usage:
                candidates.append((candidate, raw_usage[candidate]))
        for nested_key in ("prompt_tokens_details", "input_tokens_details"):
            nested = raw_usage.get(nested_key)
            if isinstance(nested, dict) and key in {"cache_read_input_tokens", "cached_input_tokens"} and "cached_tokens" in nested:
                candidates.append((f"{nested_key}.cached_tokens", nested["cached_tokens"]))
        for _, value in candidates:
                if isinstance(value, bool) or not isinstance(value, (int, str)):
                    return None
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    return None
                if isinstance(value, str) and value.strip() != str(parsed):
                    return None
                return parsed if parsed >= 0 else None
        return None
    input_tokens = read_int(input_key, ("prompt_tokens",) if protocol == "anthropic" else ("input_tokens",))
    output_tokens = read_int(output_key, ("completion_tokens",) if protocol == "anthropic" else ("output_tokens",))
    total_tokens = read_int(total_key, ("totalTokenCount",))
    cached = read_int(cache_key, ("cached_input_tokens", "prompt_cache_hit_tokens"))
    cache_write = read_int(write_key, ("cache_write_tokens",))
    present = input_tokens is not None and output_tokens is not None
    return present, input_tokens, output_tokens, total_tokens, cached, cache_write


def generate_prompt(input_tokens: int, model: str = "gpt-4o-mini") -> str:
    """Generate one deterministic prompt whose local tokenizer count matches the target when available."""
    estimator = TokenEstimator(model)
    if estimator.encoder is not None:
        return PromptFactory(estimator).build_prompt(input_tokens)
    seed = hashlib.sha256(f"vendor-billing:{input_tokens}".encode()).hexdigest()
    words = [seed[(index * 2) % len(seed):(index * 2) % len(seed) + 2] for index in range(16)]
    repetitions = max(1, input_tokens // 8)
    body = " ".join(words) + " "
    return f"Vendor billing self-test input length {input_tokens}. " + body * repetitions


def prompt_metadata(prompt: str, *, target_tokens: int | None = None, model: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"prompt_chars": len(prompt), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
    if target_tokens is not None:
        metadata["input_token_target"] = target_tokens
    if model:
        estimator = TokenEstimator(model)
        metadata["prompt_tokenizer_model"] = model
        metadata["prompt_token_count"] = estimator.count(prompt)
        metadata["prompt_token_count_exact"] = estimator.encoder is not None
    return metadata


def _decimal(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("计价数值无效")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("计价数值无效") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("计价数值必须是非负有限数")
    return number


def _money(value: Decimal) -> float:
    return float(value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP))


def _usage_int(data: dict[str, Any], key: str, *, required: bool = False) -> int | None:
    value = data.get(key)
    if value is None:
        if required:
            raise ValueError(f"usage 缺少 {key} 字段")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"usage {key} 必须是非负整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"usage {key} 必须是非负整数") from exc
    if isinstance(value, str) and value.strip() != str(parsed) or parsed < 0:
        raise ValueError(f"usage {key} 不能为负数")
    return parsed


def calculate_cost(usage: UsageEvidence | dict[str, Any], pricing: dict[str, Any]) -> dict[str, Any]:
    data = usage.as_dict() if isinstance(usage, UsageEvidence) else usage
    if not data.get("usage_present"):
        return {"verifiable": False, "reason": "usage 缺失", "total_usd": None}
    try:
        input_tokens = _usage_int(data, "input_tokens", required=True)
        output_tokens = _usage_int(data, "output_tokens", required=True)
        cached = _usage_int(data, "cached_input_tokens", required=True)
        cache_write = _usage_int(data, "cache_creation_input_tokens", required=True)
        if cached + cache_write > input_tokens and pricing.get("input_mode", "inclusive") == "inclusive":
            raise ValueError("缓存 Token 大于输入 Token")
        input_rate = _decimal(pricing.get("input_usd_per_million"))
        output_rate = _decimal(pricing.get("output_usd_per_million"))
        if cached and pricing.get("cache_read_usd_per_million") is None:
            raise ValueError("缓存读取价格缺失")
        if cache_write and pricing.get("cache_write_usd_per_million") is None:
            raise ValueError("缓存写入价格缺失")
        cache_read_rate = _decimal(pricing.get("cache_read_usd_per_million")) if cached else Decimal(0)
        cache_write_rate = _decimal(pricing.get("cache_write_usd_per_million")) if cache_write else Decimal(0)
    except ValueError as exc:
        return {"verifiable": False, "reason": str(exc), "total_usd": None}

    # inclusive: input_tokens already includes cached prompt tokens (OpenAI/Gemini).
    # exclusive: input_tokens excludes cache read/write tokens (Anthropic).
    mode = pricing.get("input_mode", "inclusive")
    if mode == "inclusive":
        ordinary_input = max(0, input_tokens - cached - cache_write)
    elif mode == "exclusive":
        ordinary_input = input_tokens
    else:
        return {"verifiable": False, "reason": f"未知 input_mode: {mode}", "total_usd": None}
    input_cost = Decimal(ordinary_input) * input_rate / Decimal(1000000)
    cache_read_cost = Decimal(cached) * cache_read_rate / Decimal(1000000)
    cache_write_cost = Decimal(cache_write) * cache_write_rate / Decimal(1000000)
    output_cost = Decimal(output_tokens) * output_rate / Decimal(1000000)
    total = input_cost + cache_read_cost + cache_write_cost + output_cost
    return {"verifiable": True, "input_mode": mode, "ordinary_input_tokens": ordinary_input,
            "cached_input_tokens": cached, "cache_creation_input_tokens": cache_write,
            "output_tokens": output_tokens, "input_cost_usd": _money(input_cost),
            "cache_read_cost_usd": _money(cache_read_cost), "cache_write_cost_usd": _money(cache_write_cost),
            "output_cost_usd": _money(output_cost), "total_usd": _money(total)}


def compare_usage(supplier: UsageEvidence | dict[str, Any], reference: UsageEvidence | dict[str, Any], pricing: dict[str, Any], *, abs_tolerance: int = 16, relative_tolerance: float = 0.05) -> dict[str, Any]:
    supplier_data = supplier.as_dict() if isinstance(supplier, UsageEvidence) else supplier
    reference_data = reference.as_dict() if isinstance(reference, UsageEvidence) else reference
    supplier_cost = calculate_cost(supplier_data, pricing)
    reference_cost = calculate_cost(reference_data, pricing)
    result = {"supplier_cost": supplier_cost, "reference_cost": reference_cost, "input_token_delta": None,
              "input_token_relative_delta": None, "cached_input_token_delta": None, "cache_creation_token_delta": None,
              "output_token_delta": None, "cost_delta_usd": None, "token_verification_status": "unverifiable",
              "pricing_verification_status": "unverifiable", "overall_status": "unverifiable",
              "output_token_observation": "unavailable", "status": "unverifiable", "reason": ""}
    if not supplier_data.get("ok") or not reference_data.get("ok"):
        result.update(status="failed", overall_status="failed", token_verification_status="failed", pricing_verification_status="unverifiable", reason="供应商或官方接口执行失败")
        return result
    if not supplier_data.get("usage_present") or not reference_data.get("usage_present"):
        result.update(status="unverifiable", overall_status="unverifiable", reason="供应商或官方接口 usage 缺失")
        return result
    try:
        supplier_input = _usage_int(supplier_data, "input_tokens", required=True)
        reference_input = _usage_int(reference_data, "input_tokens", required=True)
        supplier_output = _usage_int(supplier_data, "output_tokens", required=True)
        reference_output = _usage_int(reference_data, "output_tokens", required=True)
    except ValueError as exc:
        result.update(status="unverifiable", reason=str(exc))
        return result
    delta = abs(supplier_input - reference_input)
    relative = delta / max(1, reference_input)
    supplier_cached = _usage_int(supplier_data, "cached_input_tokens")
    reference_cached = _usage_int(reference_data, "cached_input_tokens")
    supplier_cache_write = _usage_int(supplier_data, "cache_creation_input_tokens")
    reference_cache_write = _usage_int(reference_data, "cache_creation_input_tokens")
    token_status = "passed" if delta <= abs_tolerance or relative <= relative_tolerance else "token_anomaly"
    result.update(input_token_delta=delta, input_token_relative_delta=round(relative, 8),
                  cached_input_token_delta=abs(supplier_cached - reference_cached) if supplier_cached is not None and reference_cached is not None else None,
                  cache_creation_token_delta=abs(supplier_cache_write - reference_cache_write) if supplier_cache_write is not None and reference_cache_write is not None else None,
                  output_token_delta=abs(supplier_output - reference_output),
                  token_verification_status=token_status,
                  output_token_observation="different" if supplier_output != reference_output else "same")
    pricing_verified = bool(pricing.get("verified")) and supplier_cost["verifiable"] and reference_cost["verifiable"]
    if supplier_cost["verifiable"] and reference_cost["verifiable"]:
        result["cost_delta_usd"] = _money(abs(_decimal(supplier_cost["total_usd"]) - _decimal(reference_cost["total_usd"])))
    if not pricing_verified:
        reason = supplier_cost.get("reason") or reference_cost.get("reason") or "价格规则尚未核验官方来源"
        result.update(status="pricing_unverifiable", overall_status="unverifiable", pricing_verification_status="unverifiable", reason=f"{reason}；Token 结论：{token_status}")
    elif token_status == "passed":
        result.update(pricing_verification_status="passed")
        result.update(status="passed", overall_status="passed", reason="输入 Token 差异在绝对或相对容差内；输出 Token 差异仅作观察")
    else:
        result.update(pricing_verification_status="passed")
        result.update(status="token_anomaly", overall_status="token_anomaly", reason=f"输入 Token 差异 {delta} 超过绝对容差 {abs_tolerance} 且相对差异 {relative:.2%} 超过 {relative_tolerance:.2%}")
    return result

def load_pricing_catalog(path: str | Path | None = None) -> list[dict[str, Any]]:
    catalog_path = Path(path) if path else next((candidate for candidate in (Path(__file__).resolve().parents[3] / "data" / "vendor_pricing.json", Path(__file__).resolve().parents[2] / "data" / "vendor_pricing.json") if candidate.exists()), Path(__file__).resolve().parents[3] / "data" / "vendor_pricing.json")
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("rules", []) if isinstance(data, dict) else []


def pricing_rule(rule_id: str, catalog: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    rules = catalog if catalog is not None else load_pricing_catalog()
    return next((rule for rule in rules if rule.get("id") == rule_id), None)


async def _request_once(target: dict[str, Any], prompt: str, config: dict[str, Any]) -> UsageEvidence:
    started = time.perf_counter()
    url = build_url(target["base_url"], target["endpoint"], target["protocol"], model=target["model"], enable_stream=bool(config.get("enable_stream")))
    headers = build_headers(target["protocol"], api_key=target["api_key"], anthropic_version=target.get("anthropic_version", "2023-06-01"))
    payload = build_payload(target["protocol"], endpoint=target["endpoint"], model=target["model"], prompt=prompt, max_output_tokens=int(config["max_output_tokens"]), temperature=config.get("temperature"), enable_stream=bool(config.get("enable_stream")))
    timeout = aiohttp.ClientTimeout(total=float(config.get("timeout_sec", 120)), connect=float(config.get("connect_timeout_sec", 30)))
    try:
        connector = aiohttp.TCPConnector(ssl=True)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(url, headers=headers, json=payload, allow_redirects=False) as response:
                status = response.status
                content_type = (response.headers.get("content-type") or "").lower()
                latency = None
                ttft = None
                raw_usage: dict[str, Any] = {}
                stream = bool(config.get("enable_stream")) or "text/event-stream" in content_type
                if status < 200 or status >= 300:
                    body = await response.content.read(64 * 1024)
                    message = body.decode("utf-8", errors="replace")
                    try:
                        envelope = json.loads(message)
                        if isinstance(envelope, dict):
                            error = envelope.get("error")
                            message = error.get("message") if isinstance(error, dict) else envelope.get("message", message)
                    except json.JSONDecodeError:
                        pass
                    return UsageEvidence(False, None, None, None, None, None, time.perf_counter() - started, None, status, False, f"HTTP_{status}", redact_credentials_text(" ".join(str(message).split())[:300], target.get("api_key")))

                if stream:
                    buffer = bytearray()
                    events: list[dict[str, Any]] = []
                    async for chunk in response.content.iter_chunked(16 * 1024):
                        if not chunk:
                            continue
                        buffer.extend(chunk)
                        while b"\n" in buffer:
                            line, _, remainder = bytes(buffer).partition(b"\n")
                            buffer = bytearray(remainder)
                            line = line.strip()
                            if not line.startswith(b"data:"):
                                continue
                            data = line[5:].lstrip()
                            if data == b"[DONE]":
                                continue
                            try:
                                event = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(event, dict):
                                events.append(event)
                                if ttft is None and SseStreamParser.extract_text_delta(event):
                                    ttft = time.perf_counter() - started
                    if buffer.strip().startswith(b"data:"):
                        try:
                            event = json.loads(buffer.strip()[5:].lstrip())
                            if isinstance(event, dict):
                                events.append(event)
                        except json.JSONDecodeError:
                            pass
                    usage_events = [SseStreamParser.extract_usage(event) for event in events]
                    usage_events = [usage for usage in usage_events if isinstance(usage, dict) and usage]
                    raw_usage = usage_events[-1] if usage_events else {}
                    if usage_events:
                        # Merge only evidence fields; do not synthesize missing total/cache values.
                        merged: dict[str, Any] = {}
                        for usage in usage_events:
                            merged.update(usage)
                        raw_usage = merged
                else:
                    body = await response.content.read(64 * 1024)
                    if len(body) >= 64 * 1024 and not response.content.at_eof():
                        return UsageEvidence(False, None, None, None, None, None, time.perf_counter() - started, None, status, False, "RESPONSE_TOO_LARGE", "响应超过大小限制")
                    try:
                        data = json.loads(body.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        data = None
                    if isinstance(data, dict):
                        candidate = data.get("usage") or data.get("usageMetadata")
                        raw_usage = candidate if isinstance(candidate, dict) else {}
                latency = time.perf_counter() - started
                present, input_tokens, output_tokens, total_tokens, cached, cache_write = _parse_usage_evidence(raw_usage, target["protocol"])
                return UsageEvidence(present, input_tokens, output_tokens, total_tokens, cached, cache_write, latency, ttft, status, True, raw_usage=redact_sensitive(raw_usage))
    except asyncio.TimeoutError as exc:
        return UsageEvidence(False, None, None, None, None, None, time.perf_counter() - started, None, None, False, "TIMEOUT", redact_credentials_text(exc, target.get("api_key")))
    except aiohttp.ClientError as exc:
        return UsageEvidence(False, None, None, None, None, None, time.perf_counter() - started, None, None, False, "CLIENT_ERROR", redact_credentials_text(exc, target.get("api_key")))
    except Exception as exc:
        return UsageEvidence(False, None, None, None, None, None, time.perf_counter() - started, None, None, False, "UNKNOWN", redact_credentials_text(exc, target.get("api_key")))


class VendorBillingRunner:
    def __init__(self, config: dict[str, Any], output_dir: str | Path, *, progress_callback: ProgressCallback | None = None, log_callback: LogCallback | None = None, stop_event: asyncio.Event | None = None):
        self.config = config
        self.output_dir = Path(output_dir)
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.stop_event = stop_event or asyncio.Event()

    async def _log(self, level: str, message: str) -> None:
        if self.log_callback:
            await self.log_callback(level, message)

    async def _progress(self, data: dict[str, Any]) -> None:
        if self.progress_callback:
            await self.progress_callback(data)

    async def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        catalog = load_pricing_catalog()
        rule = pricing_rule(self.config["pricing_rule_id"], catalog)
        details: list[dict[str, Any]] = []
        lengths = self.config["input_token_lengths"]
        started_at = datetime.now(timezone.utc).isoformat()
        for index, length in enumerate(lengths):
            if self.stop_event.is_set():
                break
            prompt_model = self.config.get("reference_model") or self.config.get("model") or "gpt-4o-mini"
            prompt = generate_prompt(length, prompt_model)
            metadata = prompt_metadata(prompt, target_tokens=length, model=prompt_model)
            await self._progress({"phase": "running", "current_index": index + 1, "total": len(lengths), "input_tokens": length})
            await self._log("info", f"开始自测输入长度 {length}：供应商请求")
            supplier_target = {"base_url": self.config["base_url"], "endpoint": self.config["endpoint"], "protocol": self.config["api_protocol"], "model": self.config["model"], "api_key": self.config["api_key"], "anthropic_version": self.config.get("anthropic_version", "2023-06-01")}
            reference_target = {"base_url": self.config["reference_base_url"], "endpoint": self.config["reference_endpoint"], "protocol": self.config["api_protocol"], "model": self.config["reference_model"], "api_key": self.config["reference_api_key"], "anthropic_version": self.config.get("reference_anthropic_version", "2023-06-01")}
            supplier = await _request_once(supplier_target, prompt, self.config)
            if self.stop_event.is_set():
                break
            await self._log("info", f"输入长度 {length}：官方参考请求")
            reference = await _request_once(reference_target, prompt, self.config)
            comparison = compare_usage(supplier, reference, rule, abs_tolerance=self.config.get("token_abs_tolerance", 16), relative_tolerance=self.config.get("token_relative_tolerance", 0.05)) if rule else {"status": "pricing_unverifiable", "overall_status": "unverifiable", "token_verification_status": "unverifiable", "pricing_verification_status": "unverifiable", "reason": "价格规则不存在", "supplier_cost": {"verifiable": False, "total_usd": None}, "reference_cost": {"verifiable": False, "total_usd": None}}
            details.append({"index": index + 1, "input_token_target": length, **metadata, "supplier": supplier.as_dict(), "reference": reference.as_dict(), "comparison": comparison})
            await self._progress({"phase": "completed_group", "current_index": index + 1, "total": len(lengths), "input_tokens": length, "status": comparison.get("status")})
        status_counts: dict[str, int] = {}
        for item in details:
            status = item["comparison"].get("status", "unverifiable")
            status_counts[status] = status_counts.get(status, 0) + 1
        if self.stop_event.is_set() and len(details) < len(lengths):
            overall_status = "cancelled"
        elif not details:
            overall_status = "cancelled"
        elif status_counts.get("failed"):
            overall_status = "failed"
        elif status_counts.get("pricing_unverifiable"):
            overall_status = "pricing_unverifiable"
        elif status_counts.get("token_anomaly"):
            overall_status = "token_anomaly"
        elif status_counts.get("unverifiable"):
            overall_status = "unverifiable"
        else:
            overall_status = "passed"
        safe_config = redact_sensitive({key: value for key, value in self.config.items() if key not in {"api_key", "reference_api_key"}})
        summary = {"task_kind": "vendor_billing_self_test", "status": overall_status, "config": safe_config, "pricing_rule": redact_sensitive(rule or {}), "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(), "total_groups": len(lengths), "completed_groups": len(details), "status_counts": status_counts, "details": details}
        summary_path = self.output_dir / "summary.json"
        details_path = self.output_dir / "details.jsonl"
        report_path = self.output_dir / "report.md"
        html_path = self.output_dir / "report.html"
        summary_path.write_text(json.dumps(redact_sensitive(summary), ensure_ascii=False, indent=2), encoding="utf-8")
        details_path.write_text("\n".join(json.dumps(redact_sensitive(item), ensure_ascii=False) for item in details) + ("\n" if details else ""), encoding="utf-8")
        report_path.write_text(render_markdown(summary), encoding="utf-8")
        html_path.write_text(render_html(summary), encoding="utf-8")
        return {"summary": summary, "files": {"summary_path": str(summary_path), "details_jsonl_path": str(details_path), "report_md_path": str(report_path), "report_html_path": str(html_path), "detail_count": len(details)}}


def render_markdown(summary: dict[str, Any]) -> str:
    lines = ["# 供应商接入计费自测报告", "", f"- 总体结论：**{summary.get('status')}**", f"- 完成组数：{summary.get('completed_groups')} / {summary.get('total_groups')}", "", "| 输入目标 | 供应商输入 Token | 官方输入 Token | 费用差额 USD | 状态 |", "|---:|---:|---:|---:|---|"]
    for item in summary.get("details", []):
        comparison = item.get("comparison", {})
        supplier = item.get("supplier", {})
        reference = item.get("reference", {})
        lines.append(f"| {item.get('input_token_target')} | {supplier.get('input_tokens', '—')} | {reference.get('input_tokens', '—')} | {comparison.get('cost_delta_usd', '—')} | {comparison.get('status')} |")
    return "\n".join(lines) + "\n"


def render_html(summary: dict[str, Any]) -> str:
    rows = "".join(f"<tr><td>{html.escape(str(item.get('input_token_target')))}</td><td>{html.escape(str((item.get('supplier') or {}).get('input_tokens')))}</td><td>{html.escape(str((item.get('reference') or {}).get('input_tokens')))}</td><td>{html.escape(str((item.get('comparison') or {}).get('cost_delta_usd')))}</td><td>{html.escape(str((item.get('comparison') or {}).get('status')))}</td></tr>" for item in summary.get("details", []))
    return f"<!doctype html><meta charset='utf-8'><title>供应商接入计费自测报告</title><h1>供应商接入计费自测报告</h1><p>总体结论：<strong>{html.escape(str(summary.get('status')))}</strong></p><table border='1'><tr><th>输入目标</th><th>供应商输入</th><th>官方输入</th><th>费用差额 USD</th><th>状态</th></tr>{rows}</table>"
