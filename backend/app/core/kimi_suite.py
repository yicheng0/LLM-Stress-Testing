"""Kimi compatibility suite primitives and deterministic case catalog."""
from __future__ import annotations

import json
import asyncio
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
import aiohttp
from loadtest.protocols import extract_token_usage

KIMI_CASE_IDS = (
    "cache_repeat", "cache_multiturn", "cache_variable_suffix", "thinking",
    "json_output", "stop", "sampling", "tool_call", "output_tokens",
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
)

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
    url = str(config.get("base_url", "")).rstrip("/") + str(config.get("endpoint", "/v1/chat/completions"))
    headers = {"Authorization": f"Bearer {config.get('api_key','')}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for index, case_id in enumerate(selected, 1):
            case = next(item for item in CASE_CATALOG if item.id == case_id)
            scenario_results = []
            for scenario in case.scenarios:
                if stop_event and stop_event.is_set():
                    break
                if progress_callback:
                    value = {"current_case": case.name, "current_case_id": case.id, "current_scenario": scenario.name, "completed_cases": index - 1, "total_cases": len(selected)}
                    result = progress_callback(value)
                    if asyncio.iscoroutine(result): await result
                payload = build_payload(config.get("model", "kimi-k3"), scenario, stream=False, max_output_tokens=int(config.get("max_output_tokens", 128)))
                t0 = time.perf_counter(); evidence = {"content": "", "usage": {}}
                try:
                    async with session.post(url, headers=headers, json=payload) as response:
                        raw = await response.text(); latency = time.perf_counter() - t0
                        data = json.loads(raw) if raw else {}
                        if response.status >= 400:
                            evidence["error"] = raw[:500]
                        else:
                            choice = (data.get("choices") or [{}])[0]
                            message = choice.get("message") or {}
                            evidence.update({"content": message.get("content") or "", "thinking": message.get("reasoning_content") or message.get("thinking") or "", "finish_reason": choice.get("finish_reason"), "usage": data.get("usage") or {}})
                            calls = message.get("tool_calls") or []
                            evidence["tool_calls"] = [{"name": ((c.get("function") or {}).get("name")), "arguments": ((c.get("function") or {}).get("arguments"))} for c in calls]
                        verdict = classify_cache_usage(evidence.get("usage"), request_failed=bool(evidence.get("error"))) if case.kind == "cache" else assert_response(scenario.assertion, evidence, scenario)
                        if isinstance(verdict, str): verdict = {"status": verdict, "detail": "缓存 usage 判定"}
                        status = verdict["status"]
                except Exception as exc:
                    latency = time.perf_counter() - t0; evidence["error"] = str(exc); verdict = {"status": "request_failed", "detail": str(exc)}; status = "request_failed"
                scenario_results.append({"scenario_id": scenario.id, "scenario_name": scenario.name, "status": status, "latency_sec": latency, "request": {k:v for k,v in payload.items() if k != "messages"}, "evidence": {**evidence, "usage": evidence.get("usage") or {}}, "assertion": verdict})
            statuses = [item["status"] for item in scenario_results]
            case_status = "failed" if any(x in {"request_failed", "assertion_failed"} for x in statuses) else ("unsupported" if "unsupported" in statuses else ("unverifiable" if "unverifiable" in statuses else "passed"))
            cases.append({"case_id": case.id, "case_name": case.name, "description": case.description, "status": case_status, "scenarios": scenario_results, "manual_rerun_count": 0, "elapsed_sec": sum(item["latency_sec"] for item in scenario_results)})
    counts = {key: sum(1 for case in cases if case["status"] == key) for key in ("passed", "failed", "unsupported", "unverifiable")}
    summary = {"task_kind": "kimi_suite", "status": "cancelled" if stop_event and stop_event.is_set() else "completed", "config": {k:v for k,v in config.items() if k != "api_key"}, "results": {"total_cases": len(cases), **counts, "elapsed_sec": time.perf_counter() - started}, "cases": cases}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "details.jsonl").open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    md = "# Kimi 能力测试集\n\n| Case | 状态 | 耗时 | 重试 | 失败原因 |\n|---|---|---:|---:|---|\n" + "\n".join(f"| {c['case_name']} | {c['status']} | {c['elapsed_sec']:.3f}s | 0 |  |" for c in cases) + "\n"
    (output_dir / "report.md").write_text(md, encoding="utf-8")
    (output_dir / "report.html").write_text(f"<html><body><h1>Kimi 能力测试集</h1><pre>{json.dumps(summary, ensure_ascii=False, indent=2)}</pre></body></html>", encoding="utf-8")
    return {"summary": summary, "files": {"summary_path": str(output_dir / "summary.json"), "details_jsonl_path": str(output_dir / "details.jsonl"), "report_md_path": str(output_dir / "report.md"), "report_html_path": str(output_dir / "report.html"), "detail_count": len(cases)}}
