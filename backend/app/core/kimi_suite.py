"""Kimi compatibility suite primitives and deterministic case catalog."""
from __future__ import annotations

import json
import asyncio
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
import aiohttp
from loadtest.protocols import build_headers, build_url, extract_response_text

KIMI_CASE_IDS = (
    "cache_repeat", "cache_multiturn", "cache_variable_suffix", "thinking",
    "json_output", "stop", "sampling", "tool_call", "output_tokens", "video_parse",
    "prompt_token_injection",
)

@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    prompt: str = ""
    messages: tuple[dict[str, str], ...] = ()
    overrides: dict[str, Any] = field(default_factory=dict)
    assertion: str = "basic"

@dataclass(frozen=True)
class Case:
    id: str
    name: str
    description: str
    scenarios: tuple[Scenario, ...]
    kind: str = "capability"

def _s(id: str, name: str, prompt: str, assertion: str, **overrides: Any) -> Scenario:
    return Scenario(id, name, prompt=prompt, overrides=overrides, assertion=assertion)

CASE_CATALOG = (
    Case("cache_repeat", "缓存命中-重复请求", "相同消息重复请求，观察真实缓存 usage。", (_s("repeat", "重复请求", "请回复 OK。", "cache"),), "cache"),
    Case("cache_multiturn", "缓存命中-多轮对话", "保留首轮上下文后新增一轮消息。", (Scenario("multiturn", "多轮对话", messages=(("user", "记住代号 KIMI。"), ("assistant", "已记住。"), ("user", "代号是什么？")), assertion="cache"),), "cache"),
    Case("cache_variable_suffix", "缓存命中-尾部变化", "公共前缀不变，仅改变尾部。", (_s("suffix", "尾部变化", "公共上下文：Kimi 测试。问题：尾部 A", "cache"),), "cache"),
    Case("thinking", "思考控制-多场景", "验证 thinking 开启与关闭。", (
        _s("enabled", "开启思考", "计算 17*19，并给出结果。", "thinking", thinking={"type": "enabled"}),
        _s("disabled", "关闭思考", "只输出 323。", "thinking", thinking={"type": "disabled"}),
    )),
    Case("json_output", "JSON格式输出校验-多场景", "验证 JSON 对象输出。", (
        _s("object", "JSON 对象", "输出 JSON 对象，包含 answer 字段，answer 值为 OK。", "json", response_format={"type": "json_object"}),
    )),
    Case("stop", "stop参数生效-多场景", "验证数字和中文停止序列。", (_s("digit", "数字 stop", "依次输出 1,2,3,4,5,6。", "stop", stop=["5"]), _s("han", "中文 stop", "依次输出 一、二、三、四。", "stop", stop=["三"]))),
    Case("sampling", "采样参数-多场景", "验证采样参数被接受。", (
        _s("temperature", "temperature", "用一句话介绍 Kimi。", "basic", temperature=0.2),
        _s("top_p", "top_p", "用一句话介绍 Kimi。", "basic", top_p=0.8),
    )),
    Case("tool_call", "工具调用-多场景", "验证工具名称和参数。", (_s("weather", "天气工具", "查询北京天气。", "tool", thinking={"type": "disabled"}, tools=[{"type":"function","function":{"name":"get_weather","description":"获取天气","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}], tool_choice={"type":"function","function":{"name":"get_weather"}}),)),
    Case("output_tokens", "输出tokens校验-多场景", "验证 max_tokens 上限和 usage。", tuple(_s(str(n), f"上限 {n}", "请详细解释人工智能。", "output_tokens", max_tokens=n) for n in (5, 20, 80))),
    Case("video_parse", "视频解析", "发送视频并验证模型能够返回视频内容摘要。", (_s("video", "视频理解", "请描述这个视频的主要内容，并指出关键动作。", "video_parse"),), "multimodal"),
    Case("prompt_token_injection", "Prompt Token 注入检测", "对比可见请求估算值与上游输入 Token usage。", (_s("prompt_tokens", "输入 Token 对比", "请只回复 TOKEN_CHECK_OK。", "prompt_tokens"),)),
)


def estimate_prompt_tokens(payload: dict[str, Any]) -> tuple[int | None, str]:
    """Estimate visible prompt tokens without persisting the prompt itself."""
    visible: list[str] = []

    def collect(value: Any, key: str = "") -> None:
        if key in {"model", "max_tokens", "maxOutputTokens", "stream"}:
            return
        if isinstance(value, str):
            visible.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for child_key, item in value.items():
                collect(item, child_key)

    collect(payload)
    text = "\n".join(visible)
    if not text:
        return None, "unavailable"
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text)) + 8, "tiktoken_cl100k_plus_message_overhead"
    except Exception:
        return max(1, (len(text) + 3) // 4) + 8, "char_fallback_plus_message_overhead"


def extract_input_tokens(response_or_usage: dict[str, Any] | None) -> int | None:
    if not isinstance(response_or_usage, dict):
        return None
    usage = response_or_usage.get("usage") if isinstance(response_or_usage.get("usage"), dict) else response_or_usage
    if isinstance(response_or_usage.get("usageMetadata"), dict):
        usage = response_or_usage["usageMetadata"]
    for key in ("prompt_tokens", "input_tokens", "promptTokenCount"):
        if key in usage and usage[key] is not None:
            try:
                return int(usage[key])
            except (TypeError, ValueError):
                return None
    return None


def assert_prompt_token_evidence(local_tokens: int | None, upstream_tokens: int | None, *, supported: bool = True, tolerance_tokens: int = 16, tolerance_ratio: float = 0.25) -> dict[str, Any]:
    evidence = {"local_prompt_tokens": local_tokens, "upstream_input_tokens": upstream_tokens, "delta_tokens": None, "delta_ratio": None, "tolerance_tokens": tolerance_tokens, "tolerance_ratio": tolerance_ratio}
    if not supported:
        return {**evidence, "status": "unsupported", "detail": "当前协议未提供可比较的输入 Token 字段"}
    if local_tokens is None:
        return {**evidence, "status": "unverifiable", "detail": "本地 Prompt Token 估算不可用"}
    if upstream_tokens is None:
        return {**evidence, "status": "unverifiable", "detail": "上游响应缺少输入 Token usage"}
    delta = upstream_tokens - local_tokens
    ratio = delta / max(local_tokens, 1)
    evidence.update({"delta_tokens": delta, "delta_ratio": ratio})
    suspicious = delta > tolerance_tokens and ratio > tolerance_ratio
    return {**evidence, "status": "suspected_injection" if suspicious else "passed", "detail": f"本地估算 {local_tokens}，上游 {upstream_tokens}，差值 {delta}（{ratio:.1%}）"}


def build_protocol_request(config: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    protocol = str(config.get("api_protocol") or "openai")
    model = str(config.get("model") or "kimi-k3")
    stream = bool(config.get("enable_stream", True))
    max_tokens = int(config.get("max_output_tokens", 128))
    messages = [{"role": "system", "content": "You are a benchmarking target."}]
    if scenario.id == "video":
        messages.append({"role": "user", "content": [{"type": "text", "text": scenario.prompt}, {"type": "video_url", "video_url": {"url": str(config.get("video_data_url") or "")}}]})
    elif scenario.messages:
        messages.extend({"role": role, "content": content} for role, content in scenario.messages)
    else:
        messages.append({"role": "user", "content": scenario.prompt})
    if protocol == "gemini":
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": scenario.prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if scenario.overrides.get("temperature") is not None:
            payload["generationConfig"]["temperature"] = scenario.overrides["temperature"]
    elif protocol == "anthropic":
        payload = {"model": model, "system": messages[0]["content"], "messages": messages[1:], "max_tokens": max_tokens, "stream": stream}
        if scenario.overrides.get("temperature") is not None:
            payload["temperature"] = scenario.overrides["temperature"]
    else:
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": stream}
    payload.update(scenario.overrides)
    if protocol == "gemini":
        payload.pop("model", None)
        payload.pop("stream", None)
        payload.pop("max_tokens", None)
    return {
        "url": build_url(str(config.get("base_url") or ""), str(config.get("endpoint") or ""), protocol, model=model, enable_stream=stream),
        "headers": build_headers(protocol, api_key=str(config.get("api_key") or "")),
        "payload": payload,
    }


def build_progress_snapshot(cases: list[dict[str, Any]], *, current_case: str | None = None, current_case_id: str | None = None, current_scenario: str | None = None, total_cases: int | None = None) -> dict[str, Any]:
    return {
        "current_case": current_case,
        "current_case_id": current_case_id,
        "current_scenario": current_scenario,
        "completed_cases": sum(1 for item in cases if item.get("status") not in {"pending", "running"}),
        "total_cases": total_cases if total_cases is not None else len(cases),
        "cases": cases,
    }

def validate_case_ids(case_ids: list[str] | tuple[str, ...]) -> list[str]:
    result = list(dict.fromkeys(case_ids))
    if not result:
        raise ValueError("至少选择一个 Kimi Case")
    unknown = [x for x in result if x not in KIMI_CASE_IDS]
    if unknown:
        raise ValueError(f"未知 Kimi Case: {', '.join(unknown)}")
    return result

def build_payload(model: str, scenario: Scenario, *, stream: bool = True, max_output_tokens: int = 128) -> dict[str, Any]:
    messages = [{"role": "system", "content": "You are a benchmarking target."}]
    if scenario.messages:
        messages.extend({"role": role, "content": content} for role, content in scenario.messages)
    else:
        messages.append({"role": "user", "content": scenario.prompt})
    body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_output_tokens, "stream": stream}
    body.update(scenario.overrides)
    return body

def assert_response(kind: str, evidence: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    content = str(evidence.get("content") or "")
    if evidence.get("error"):
        return {"status": "request_failed", "detail": evidence["error"]}
    if evidence.get("unsupported"):
        return {"status": "unsupported", "detail": evidence.get("unsupported")}
    if kind == "video_parse":
        return {"status": "passed" if len(content.strip()) >= 4 else "unverifiable", "detail": "视频解析返回了文本摘要"}
    if kind == "json":
        try:
            value = json.loads(content)
            return {"status": "passed" if isinstance(value, dict) and "answer" in value else "assertion_failed", "detail": "JSON object with answer required"}
        except (TypeError, ValueError):
            return {"status": "assertion_failed", "detail": "响应不是合法 JSON"}
    if kind == "stop":
        forbidden = {"5": ["6"], "三": ["四"]}
        bad = [x for x in forbidden.get((scenario.overrides.get("stop") or [""])[0], []) if x in content]
        return {"status": "assertion_failed" if bad else "passed", "detail": f"forbidden={bad}"}
    if kind == "tool":
        calls = evidence.get("tool_calls") or []
        if not calls or calls[0].get("name") != "get_weather":
            return {"status": "assertion_failed", "detail": "缺少 get_weather 工具调用"}
        try:
            args = json.loads(calls[0].get("arguments", "{}"))
        except (TypeError, ValueError):
            return {"status": "assertion_failed", "detail": "工具参数不是 JSON"}
        return {"status": "passed" if args.get("city") else "assertion_failed", "detail": "city 参数必填"}
    if kind == "thinking":
        has_thinking = bool(evidence.get("thinking"))
        enabled = scenario.overrides.get("thinking", {}).get("type") == "enabled"
        return {"status": "passed" if has_thinking == enabled else "unverifiable", "detail": f"thinking_observed={has_thinking}"}
    if kind == "output_tokens":
        usage = evidence.get("usage") or {}
        if "completion_tokens" not in usage and "output_tokens" not in usage:
            return {"status": "unverifiable", "detail": "缺少输出 Token usage"}
        value = usage.get("completion_tokens", usage.get("output_tokens", 0))
        limit = scenario.overrides.get("max_tokens", 128)
        return {"status": "passed" if value <= limit else "assertion_failed", "detail": f"output_tokens={value}, limit={limit}"}
    return {"status": "passed" if content or evidence.get("tool_calls") is not None else "unverifiable", "detail": "有效响应"}

def classify_cache_usage(usage: dict[str, Any] | None, *, request_failed: bool = False) -> str:
    if request_failed:
        return "request_failed"
    if not isinstance(usage, dict):
        return "unverifiable"
    if "prompt_tokens_details" not in usage and "cached_input_tokens" not in usage and "prompt_cache_hit_tokens" not in usage:
        return "unverifiable"
    cached = usage.get("prompt_cache_hit_tokens", usage.get("cached_input_tokens", (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)))
    return "cache_hit" if int(cached or 0) > 0 else "cache_miss"

async def run_kimi_suite(config: dict[str, Any], output_dir: Path, *, stop_event=None, progress_callback=None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = validate_case_ids(config.get("case_ids") or list(KIMI_CASE_IDS))
    cases = []
    started = time.perf_counter()
    timeout = aiohttp.ClientTimeout(total=float(config.get("timeout_sec", 120)))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        live_cases: list[dict[str, Any]] = [{"case_id": item.id, "case_name": item.name, "status": "pending", "elapsed_sec": 0, "scenarios": [], "manual_rerun_count": 0} for item in CASE_CATALOG if item.id in selected]
        for index, case_id in enumerate(selected, 1):
            case = next(item for item in CASE_CATALOG if item.id == case_id)
            live_case = next(item for item in live_cases if item["case_id"] == case.id)
            live_case["status"] = "running"
            scenario_results = []
            for scenario in case.scenarios:
                if stop_event and stop_event.is_set():
                    break
                if progress_callback:
                    value = build_progress_snapshot(live_cases, current_case=case.name, current_case_id=case.id, current_scenario=scenario.name, total_cases=len(selected))
                    result = progress_callback(value)
                    if asyncio.iscoroutine(result): await result
                request = build_protocol_request({**config, "enable_stream": False}, scenario)
                payload = request["payload"]
                t0 = time.perf_counter(); evidence = {"content": "", "usage": {}}
                try:
                    async with session.post(request["url"], headers=request["headers"], json=payload) as response:
                        raw = await response.text(); latency = time.perf_counter() - t0
                        data = json.loads(raw) if raw else {}
                        if response.status >= 400:
                            evidence["error"] = raw[:500]
                        else:
                            choice = (data.get("choices") or [{}])[0]
                            message = choice.get("message") or {}
                            evidence.update({"content": extract_response_text(data), "thinking": message.get("reasoning_content") or message.get("thinking") or "", "finish_reason": choice.get("finish_reason"), "usage": data.get("usage") or data.get("usageMetadata") or {}})
                            calls = message.get("tool_calls") or []
                            evidence["tool_calls"] = [{"name": ((c.get("function") or {}).get("name")), "arguments": ((c.get("function") or {}).get("arguments"))} for c in calls]
                        if case.kind == "cache":
                            verdict = classify_cache_usage(evidence.get("usage"), request_failed=bool(evidence.get("error")))
                        elif scenario.assertion == "prompt_tokens":
                            local_tokens, estimation_method = estimate_prompt_tokens(payload)
                            upstream_tokens = extract_input_tokens(data) if not evidence.get("error") else None
                            verdict = assert_prompt_token_evidence(local_tokens, upstream_tokens, supported=True)
                            verdict["estimation_method"] = estimation_method
                            evidence["token_evidence"] = verdict
                        else:
                            verdict = assert_response(scenario.assertion, evidence, scenario)
                        if isinstance(verdict, str): verdict = {"status": verdict, "detail": "缓存 usage 判定"}
                        status = verdict["status"]
                except Exception as exc:
                    latency = time.perf_counter() - t0; evidence["error"] = str(exc); verdict = {"status": "request_failed", "detail": str(exc)}; status = "request_failed"
                request_summary = {k: v for k, v in payload.items() if k not in {"messages", "contents", "system", "input"}}
                scenario_results.append({"scenario_id": scenario.id, "scenario_name": scenario.name, "status": status, "latency_sec": latency, "request": request_summary, "evidence": {**evidence, "usage": evidence.get("usage") or {}}, "assertion": verdict})
                live_case["scenarios"] = scenario_results
                live_case["elapsed_sec"] = sum(item["latency_sec"] for item in scenario_results)
                if progress_callback:
                    await progress_callback(build_progress_snapshot(live_cases, current_case=case.name, current_case_id=case.id, current_scenario=scenario.name, total_cases=len(selected)))
            statuses = [item["status"] for item in scenario_results]
            case_status = "failed" if any(x in {"request_failed", "assertion_failed"} for x in statuses) else ("suspected_injection" if "suspected_injection" in statuses else ("unsupported" if "unsupported" in statuses else ("unverifiable" if "unverifiable" in statuses else "passed")))
            cases.append({"case_id": case.id, "case_name": case.name, "description": case.description, "status": case_status, "scenarios": scenario_results, "manual_rerun_count": 0, "elapsed_sec": sum(item["latency_sec"] for item in scenario_results)})
            live_case.update({"status": case_status, "scenarios": scenario_results, "elapsed_sec": sum(item["latency_sec"] for item in scenario_results)})
            if progress_callback:
                await progress_callback(build_progress_snapshot(live_cases, current_case=None, current_case_id=None, current_scenario=None, total_cases=len(selected)))
    counts = {key: sum(1 for case in cases if case["status"] == key) for key in ("passed", "failed", "unsupported", "unverifiable")}
    summary = {"task_kind": "kimi_suite", "status": "cancelled" if stop_event and stop_event.is_set() else "completed", "config": {k:v for k,v in config.items() if k not in {"api_key", "video_data_url"}}, "results": {"total_cases": len(cases), **counts, "elapsed_sec": time.perf_counter() - started}, "cases": cases}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "details.jsonl").open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    md = "# Kimi 能力测试集\n\n| Case | 状态 | 耗时 | 重试 | 失败原因 |\n|---|---|---:|---:|---|\n" + "\n".join(f"| {c['case_name']} | {c['status']} | {c['elapsed_sec']:.3f}s | 0 |  |" for c in cases) + "\n"
    (output_dir / "report.md").write_text(md, encoding="utf-8")
    (output_dir / "report.html").write_text(f"<html><body><h1>Kimi 能力测试集</h1><pre>{json.dumps(summary, ensure_ascii=False, indent=2)}</pre></body></html>", encoding="utf-8")
    return {"summary": summary, "files": {"summary_path": str(output_dir / "summary.json"), "details_jsonl_path": str(output_dir / "details.jsonl"), "report_md_path": str(output_dir / "report.md"), "report_html_path": str(output_dir / "report.html"), "detail_count": len(cases)}}
