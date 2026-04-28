#!/usr/bin/env python3
"""
LLM API 压测脚本（OpenAI 兼容接口）

目标能力：
- 控制并发（例如 200）
- 构造大输入（例如 100k tokens 级别）
- 统计延迟、吞吐、TPM、成功率、错误码分布
- 支持限速、预热、持续压测、失败重试
- 输出 JSON 明细和 Markdown 摘要

示例：
python load_test_llm_api.py \
  --base-url https://your-openai-compatible-endpoint/v1 \
  --api-key $API_KEY \
  --model your-model \
  --endpoint /chat/completions \
  --concurrency 200 \
  --duration-sec 300 \
  --input-tokens 100000 \
  --max-output-tokens 128 \
  --temperature 0 \
  --timeout-sec 600 \
  --output-dir ./results
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import string
import sys
import time
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import aiohttp

try:
    import tiktoken
except ImportError:
    tiktoken = None


LOREM = (
    "Large language model load testing requires stable prompts, good observability, "
    "careful concurrency control, retry policies, and accurate token accounting. "
    "This synthetic corpus is repeated to generate long prompts for pressure testing. "
)


@dataclass
class RequestResult:
    request_id: int
    ok: bool
    status: int
    started_at: float
    ended_at: float
    latency_sec: float
    ttft_sec: Optional[float]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    error_type: Optional[str]
    error_message: Optional[str]
    retry_count: int


@dataclass(frozen=True)
class ProtocolSpec:
    name: str
    label: str
    default_base_url: str
    stream_endpoint: str
    non_stream_endpoint: str
    default_model: str

    def default_endpoint(self, enable_stream: bool) -> str:
        return self.stream_endpoint if enable_stream else self.non_stream_endpoint


PROTOCOL_SPECS: Dict[str, ProtocolSpec] = {
    "openai": ProtocolSpec(
        name="openai",
        label="OpenAI-compatible",
        default_base_url="https://api.example.com/v1",
        stream_endpoint="/chat/completions",
        non_stream_endpoint="/chat/completions",
        default_model="glm-5.1",
    ),
    "anthropic": ProtocolSpec(
        name="anthropic",
        label="Anthropic Messages",
        default_base_url="https://api.anthropic.com/v1",
        stream_endpoint="/messages",
        non_stream_endpoint="/messages",
        default_model="claude-sonnet-4-20250514",
    ),
    "gemini": ProtocolSpec(
        name="gemini",
        label="Gemini API",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        stream_endpoint="/models/{model}:streamGenerateContent?alt=sse",
        non_stream_endpoint="/models/{model}:generateContent",
        default_model="gemini-2.5-pro",
    ),
}

LEGACY_DEFAULT_ENDPOINTS = {"/chat/completions", "/responses", "/messages"}


class TokenEstimator:
    def __init__(self, model: str):
        self.model = model
        self.encoder = None
        if tiktoken is not None:
            try:
                self.encoder = tiktoken.encoding_for_model(model)
            except Exception:
                try:
                    self.encoder = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    self.encoder = None

    def count(self, text: str) -> int:
        if self.encoder is not None:
            return len(self.encoder.encode(text))
        # 粗略估算：英文约 4 字符/token；中文这里不做精确估计。
        return max(1, math.ceil(len(text) / 4))


class PromptFactory:
    def __init__(self, estimator: TokenEstimator):
        self.estimator = estimator

    def build_prompt(self, target_tokens: int) -> str:
        # 生成近似 target_tokens 的长文本。为了减小 CPU 消耗，先拼接大块再微调。
        base = []
        seed_block = (LOREM * 200).strip()
        block_tokens = self.estimator.count(seed_block)
        repeat = max(1, target_tokens // max(1, block_tokens))
        for i in range(repeat):
            base.append(f"[BLOCK {i}] {seed_block}")
        prompt = "\n".join(base)

        current = self.estimator.count(prompt)
        filler_idx = 0
        while current < target_tokens:
            filler = (
                f"\n[FILLER {filler_idx}] "
                "Please summarize the operational stability implications of high-concurrency LLM serving, "
                "including queueing delay, rate limiting, token budget enforcement, KV cache pressure, "
                "and tail latency amplification under burst load."
            )
            prompt += filler
            current = self.estimator.count(prompt)
            filler_idx += 1

        return prompt


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]
LogCallback = Callable[[str, str], Awaitable[None] | None]


class LoadTester:
    def __init__(
        self,
        args: argparse.Namespace,
        progress_callback: Optional[ProgressCallback] = None,
        stop_event: Optional[asyncio.Event] = None,
        log_callback: Optional[LogCallback] = None,
    ):
        self.args = args
        self.progress_callback = progress_callback
        self.stop_event = stop_event
        self.log_callback = log_callback
        self.estimator = TokenEstimator(args.model)
        self.prompt_factory = PromptFactory(self.estimator)
        print(f"[*] 正在构建 {args.input_tokens} token 输入 prompt...", flush=True)
        self.prompt = self.prompt_factory.build_prompt(args.input_tokens)
        self.actual_input_tokens = self.estimator.count(self.prompt)
        print(f"[*] Prompt 构建完成，实际 token 数: {self.actual_input_tokens}", flush=True)
        self.results: List[RequestResult] = []
        self.stop_at = 0.0
        self.request_counter = 0
        self.counter_lock = asyncio.Lock()
        self.test_start_time = time.perf_counter()  # 新增：记录测试开始时间
        self.last_progress_emit_at = 0.0

    @staticmethod
    async def _maybe_await(value: Any) -> None:
        if asyncio.iscoroutine(value):
            await value

    def should_stop(self) -> bool:
        return bool(self.stop_event and self.stop_event.is_set())

    async def emit_log(self, level: str, message: str) -> None:
        if self.log_callback:
            await self._maybe_await(self.log_callback(level, message))

    async def emit_progress(self, force: bool = False) -> None:
        if not self.progress_callback:
            return

        now = time.time()
        total = len(self.results)
        if not force and total % 10 != 0 and now - self.last_progress_emit_at < 2:
            return

        success = [r for r in self.results if r.ok]
        failed = total - len(success)
        elapsed = max(0.001, now - (self.stop_at - self.args.duration_sec)) if self.stop_at else 0.001
        recent_success = [r for r in self.results[-10:] if r.ok]
        recent_latency = statistics.mean([r.latency_sec for r in recent_success]) if recent_success else 0.0
        total_tokens = sum(r.total_tokens for r in success)

        self.last_progress_emit_at = now
        await self._maybe_await(self.progress_callback({
            "completed_requests": total,
            "successful_requests": len(success),
            "failed_requests": failed,
            "success_rate": round(len(success) / total, 4) if total else 0.0,
            "current_qps": round(len(success) / elapsed, 4),
            "current_rpm": round(len(success) * 60 / elapsed, 4),
            "current_tpm": round(total_tokens * 60 / elapsed, 4),
            "avg_latency_sec": round(recent_latency, 4),
            "elapsed_sec": round(elapsed, 2),
        }))

    async def next_request_id(self) -> int:
        async with self.counter_lock:
            self.request_counter += 1
            return self.request_counter

    def api_protocol(self) -> str:
        return getattr(self.args, "api_protocol", "openai")

    def protocol_spec(self) -> ProtocolSpec:
        return PROTOCOL_SPECS.get(self.api_protocol(), PROTOCOL_SPECS["openai"])

    def build_payload(self) -> Dict[str, Any]:
        protocol = self.api_protocol()
        if protocol == "gemini":
            return {
                "systemInstruction": {
                    "parts": [
                        {"text": "You are a benchmarking target. Return a concise deterministic answer."}
                    ]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": self.prompt}
                        ],
                    },
                ],
                "generationConfig": {
                    "maxOutputTokens": self.args.max_output_tokens,
                    "temperature": self.args.temperature,
                },
            }

        if protocol == "anthropic":
            return {
                "model": self.args.model,
                "system": "You are a benchmarking target. Return a concise deterministic answer.",
                "messages": [
                    {
                        "role": "user",
                        "content": self.prompt,
                    },
                ],
                "max_tokens": self.args.max_output_tokens,
                "temperature": self.args.temperature,
                "stream": self.args.enable_stream,
            }

        # 默认按 chat.completions 格式发送；也支持 responses 接口。
        if self.args.endpoint.endswith("/responses"):
            return {
                "model": self.args.model,
                "input": self.prompt,
                "max_output_tokens": self.args.max_output_tokens,
                "temperature": self.args.temperature,
                "stream": self.args.enable_stream,
            }

        return {
            "model": self.args.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a benchmarking target. Return a concise deterministic answer.",
                },
                {
                    "role": "user",
                    "content": self.prompt,
                },
            ],
            "max_tokens": self.args.max_output_tokens,
            "temperature": self.args.temperature,
            "stream": self.args.enable_stream,
        }

    def build_headers(self) -> Dict[str, str]:
        protocol = self.api_protocol()
        if protocol == "gemini":
            return {
                "x-goog-api-key": self.args.api_key,
                "Content-Type": "application/json",
            }

        if protocol == "anthropic":
            return {
                "x-api-key": self.args.api_key,
                "anthropic-version": getattr(self.args, "anthropic_version", "2023-06-01"),
                "Content-Type": "application/json",
            }

        return {
            "Authorization": f"Bearer {self.args.api_key}",
            "Content-Type": "application/json",
        }

    def build_url(self) -> str:
        endpoint = self.args.endpoint
        spec = self.protocol_spec()
        if self.api_protocol() == "gemini":
            if not endpoint or endpoint in LEGACY_DEFAULT_ENDPOINTS:
                endpoint = spec.default_endpoint(self.args.enable_stream)
            endpoint = endpoint.replace("{model}", self.args.model)
        return self.args.base_url.rstrip("/") + endpoint

    @staticmethod
    def _extract_tokens(usage: dict) -> tuple[int, int]:
        """从 usage 字典中提取 output_tokens 和 total_tokens"""
        output_tokens = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("candidatesTokenCount")
            or 0
        )
        input_tokens = int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("promptTokenCount")
            or 0
        )
        total_tokens = int(usage.get("total_tokens") or usage.get("totalTokenCount") or 0)
        if total_tokens <= 0 and (input_tokens or output_tokens):
            total_tokens = input_tokens + output_tokens
        return output_tokens, total_tokens

    def _create_result(
        self,
        request_id: int,
        started_at: float,
        t0: float,
        ok: bool,
        status: int = 0,
        ttft: Optional[float] = None,
        output_tokens: int = 0,
        total_tokens: Optional[int] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        attempt: int = 1,
    ) -> RequestResult:
        """统一创建 RequestResult 对象"""
        if total_tokens is None:
            total_tokens = self.actual_input_tokens + output_tokens

        return RequestResult(
            request_id=request_id,
            ok=ok,
            status=status,
            started_at=started_at,
            ended_at=time.perf_counter(),
            latency_sec=time.perf_counter() - t0,
            ttft_sec=ttft,
            input_tokens=self.actual_input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            error_type=error_type,
            error_message=error_message,
            retry_count=attempt - 1,
        )

    async def send_one(self, session: aiohttp.ClientSession, request_id: int) -> RequestResult:
        url = self.build_url()
        headers = self.build_headers()
        payload = self.build_payload()

        attempt = 0
        started_at = time.perf_counter()  # 修改：使用 perf_counter
        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                async with session.post(url, headers=headers, json=payload, timeout=self.args.timeout_sec) as resp:

                    if 200 <= resp.status < 300:
                        # 流式响应处理
                        if self.args.enable_stream:
                            ttft = None
                            chunks = []
                            output_tokens = 0
                            total_tokens = 0

                            try:
                                async for chunk in resp.content.iter_any():
                                    if ttft is None and chunk:
                                        ttft = time.perf_counter() - t0
                                    chunks.append(chunk)

                                t1 = time.perf_counter()
                                latency = t1 - t0

                                # 解析 SSE 流
                                full_text = b''.join(chunks).decode('utf-8', errors='ignore')
                                output_tokens, total_tokens = self._parse_stream_usage(full_text)

                                return self._create_result(
                                    request_id=request_id,
                                    started_at=started_at,
                                    t0=t0,
                                    ok=True,
                                    status=resp.status,
                                    ttft=ttft,
                                    output_tokens=output_tokens,
                                    total_tokens=total_tokens if total_tokens > 0 else None,
                                    attempt=attempt,
                                )
                            except Exception as e:
                                return self._create_result(
                                    request_id=request_id,
                                    started_at=started_at,
                                    t0=t0,
                                    ok=False,
                                    status=resp.status,
                                    ttft=ttft,
                                    output_tokens=0,
                                    total_tokens=self.actual_input_tokens,
                                    error_type="STREAM_PARSE_ERROR",
                                    error_message=f"流式响应解析失败: {str(e)}",
                                    attempt=attempt,
                                )

                        # 非流式响应处理（保持向后兼容）
                        else:
                            text = await resp.text()
                            t1 = time.perf_counter()
                            latency = t1 - t0

                            output_tokens = 0
                            total_tokens = 0
                            try:
                                data = json.loads(text)
                                usage = {}
                                if isinstance(data, dict):
                                    usage = data.get("usage") or data.get("usageMetadata") or {}
                                output_tokens, total_tokens = self._extract_tokens(usage)
                            except Exception:
                                data = None

                            return self._create_result(
                                request_id=request_id,
                                started_at=started_at,
                                t0=t0,
                                ok=True,
                                status=resp.status,
                                ttft=None,
                                output_tokens=output_tokens,
                                total_tokens=total_tokens if total_tokens > 0 else None,
                                attempt=attempt,
                            )

                    # 处理错误响应
                    text = await resp.text()
                    t1 = time.perf_counter()
                    latency = t1 - t0

                    # 可重试状态码
                    retryable = resp.status in {408, 409, 429, 500, 502, 503, 504}
                    if retryable and attempt <= self.args.max_retries:
                        await asyncio.sleep(self.backoff(attempt))
                        continue

                    return self._create_result(
                        request_id=request_id,
                        started_at=started_at,
                        t0=t0,
                        ok=False,
                        status=resp.status,
                        output_tokens=0,
                        total_tokens=self.actual_input_tokens,
                        error_type=f"HTTP_{resp.status}",
                        error_message=text[:1000],
                        attempt=attempt,
                    )
            except asyncio.TimeoutError as e:
                if attempt <= self.args.max_retries:
                    await asyncio.sleep(self.backoff(attempt))
                    continue
                return self._create_result(
                    request_id=request_id,
                    started_at=started_at,
                    t0=t0,
                    ok=False,
                    status=0,
                    output_tokens=0,
                    total_tokens=self.actual_input_tokens,
                    error_type="TIMEOUT",
                    error_message=str(e),
                    attempt=attempt,
                )
            except aiohttp.ClientError as e:
                if attempt <= self.args.max_retries:
                    await asyncio.sleep(self.backoff(attempt))
                    continue
                return self._create_result(
                    request_id=request_id,
                    started_at=started_at,
                    t0=t0,
                    ok=False,
                    status=0,
                    output_tokens=0,
                    total_tokens=self.actual_input_tokens,
                    error_type="CLIENT_ERROR",
                    error_message=str(e),
                    attempt=attempt,
                )
            except Exception as e:
                return self._create_result(
                    request_id=request_id,
                    started_at=started_at,
                    t0=t0,
                    ok=False,
                    status=0,
                    output_tokens=0,
                    total_tokens=self.actual_input_tokens,
                    error_type="UNKNOWN",
                    error_message=str(e),
                    attempt=attempt,
                )

    def _parse_stream_usage(self, stream_text: str) -> tuple[int, int]:
        """
        解析 SSE 流中的 usage 信息

        OpenAI 格式示例：
        data: {"choices":[{"delta":{"content":"Hello"}}]}
        data: {"choices":[{"delta":{}}],"usage":{"completion_tokens":10,"total_tokens":110}}
        data: [DONE]

        返回: (output_tokens, total_tokens)
        """
        output_tokens = 0
        total_tokens = 0
        input_tokens = 0

        for line in stream_text.split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                data_str = line[6:]  # 去掉 "data: " 前缀
                if data_str == '[DONE]':
                    break
                try:
                    data = json.loads(data_str)
                    if isinstance(data, dict):
                        usage = data.get('usage')
                        if not usage:
                            usage = data.get("usageMetadata")
                        if not usage and isinstance(data.get("message"), dict):
                            usage = data["message"].get("usage")
                        if isinstance(usage, dict):
                            input_tokens = int(
                                usage.get("prompt_tokens")
                                or usage.get("input_tokens")
                                or usage.get("promptTokenCount")
                                or input_tokens
                                or 0
                            )
                            output_tokens = int(
                                usage.get("completion_tokens")
                                or usage.get("output_tokens")
                                or usage.get("candidatesTokenCount")
                                or output_tokens
                                or 0
                            )
                            total_tokens = int(
                                usage.get("total_tokens")
                                or usage.get("totalTokenCount")
                                or total_tokens
                                or 0
                            )
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue

        if total_tokens <= 0 and (input_tokens or output_tokens):
            total_tokens = input_tokens + output_tokens
        return output_tokens, total_tokens

    def backoff(self, attempt: int) -> float:
        base = min(self.args.retry_backoff_base * (2 ** (attempt - 1)), self.args.retry_backoff_max)
        jitter = random.uniform(0, base * 0.2)
        return base + jitter

    async def worker(self, worker_id: int, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore):
        while time.time() < self.stop_at and not self.should_stop():
            async with semaphore:
                if self.should_stop():
                    break
                req_id = await self.next_request_id()
                result = await self.send_one(session, req_id)
                self.results.append(result)
                await self.emit_progress()

                # 实时统计
                elapsed = int(time.time() - (self.stop_at - self.args.duration_sec))
                total = len(self.results)
                success = sum(1 for r in self.results if r.ok)
                current_success_rate = success / total * 100 if total > 0 else 0

                # 只输出失败请求和每10个请求的汇总
                if not result.ok:
                    # 输出失败请求的详细信息
                    error_msg = result.error_message[:200] if result.error_message else "Unknown error"
                    print(f"  [{elapsed:>4}s] req#{result.request_id} FAIL({result.error_type}) "
                          f"status={result.status} latency={result.latency_sec:.2f}s msg={error_msg}", flush=True)
                    await self.emit_log(
                        "error",
                        f"req#{result.request_id} FAIL({result.error_type}) status={result.status} "
                        f"latency={result.latency_sec:.2f}s msg={error_msg}",
                    )

                # 每 10 个请求输出一次汇总
                if total % 10 == 0:
                    recent_latencies = [r.latency_sec for r in self.results[-10:] if r.ok]
                    avg_latency = statistics.mean(recent_latencies) if recent_latencies else 0
                    print(f"  [{elapsed:>4}s] 已完成={total}, 成功={success}, 成功率={current_success_rate:.1f}%, "
                          f"近10次平均延迟={avg_latency:.2f}s", flush=True)
                    await self.emit_log(
                        "info",
                        f"已完成={total}, 成功={success}, 成功率={current_success_rate:.1f}%, "
                        f"近10次平均延迟={avg_latency:.2f}s",
                    )
            if self.args.think_time_ms > 0:
                await asyncio.sleep(self.args.think_time_ms / 1000.0)

    async def run(self) -> Dict[str, Any]:
        connector = aiohttp.TCPConnector(limit=0, ssl=False)
        semaphore = asyncio.Semaphore(self.args.concurrency)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.args.connect_timeout_sec)

        self.stop_at = time.time() + self.args.duration_sec
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 预热
            warmup_results = []
            if self.args.warmup_requests > 0 and not self.should_stop():
                print(f"[*] 开始预热，发送 {self.args.warmup_requests} 个预热请求...", flush=True)
                await self.emit_log("info", f"开始预热，发送 {self.args.warmup_requests} 个预热请求")
                warm_tasks = []
                for _ in range(self.args.warmup_requests):
                    req_id = await self.next_request_id()
                    warm_tasks.append(self.send_one(session, req_id))
                warmup_results = await asyncio.gather(*warm_tasks, return_exceptions=False)

                # 不计入正式结果
                # self.results.extend(warmup_results)  # 删除这行

                warmup_success = sum(1 for r in warmup_results if r.ok)
                print(f"[*] 预热完成，成功 {warmup_success}/{len(warmup_results)}", flush=True)
                await self.emit_log("info", f"预热完成，成功 {warmup_success}/{len(warmup_results)}")

                # 如果预热全部失败，输出第一个错误详情
                if warmup_success == 0 and warmup_results:
                    first_error = warmup_results[0]
                    print(f"[!] 预热请求全部失败！第一个错误: {first_error.error_type}", flush=True)
                    print(f"[!] 错误详情: {first_error.error_message[:500]}", flush=True)
                    print(f"[!] HTTP状态码: {first_error.status}", flush=True)
                    await self.emit_log("error", f"预热请求全部失败：{first_error.error_type}")

            # 正式压测
            print(f"[*] 开始正式压测，并发={self.args.concurrency}，时长={self.args.duration_sec}s ...", flush=True)
            await self.emit_log("info", f"开始正式压测，并发={self.args.concurrency}，时长={self.args.duration_sec}s")
            await self.emit_progress(force=True)
            tasks = [
                asyncio.create_task(self.worker(i, session, semaphore))
                for i in range(self.args.concurrency)
            ]
            await asyncio.gather(*tasks)
        print(f"[*] 压测结束，正在汇总结果...", flush=True)
        await self.emit_progress(force=True)
        await self.emit_log("info", "压测结束，正在汇总结果")
        return self.summarize()

    async def run_matrix(self) -> list[Dict[str, Any]]:
        """
        运行矩阵测试：多个输入规模 × 多个并发级别

        返回：每个测试点的 summary 列表
        """
        input_tokens_list = [int(x.strip()) for x in self.args.input_tokens_list.split(',')]
        concurrency_list = [int(x.strip()) for x in self.args.concurrency_list.split(',')]

        results_matrix = []
        total_tests = len(input_tokens_list) * len(concurrency_list)
        current_test = 0

        print(f"[*] 矩阵测试模式：{len(input_tokens_list)} 个输入规模 × {len(concurrency_list)} 个并发级别 = {total_tests} 个测试点")
        print(f"[*] 每个测试点持续 {self.args.matrix_duration_sec} 秒")
        await self.emit_log("info", f"矩阵测试模式：{total_tests} 个测试点，每点 {self.args.matrix_duration_sec} 秒")

        for input_tokens in input_tokens_list:
            for concurrency in concurrency_list:
                if self.should_stop():
                    await self.emit_log("warning", "矩阵测试收到停止信号，跳过剩余测试点")
                    break

                current_test += 1
                print(f"\n{'='*80}")
                print(f"[*] 测试点 {current_test}/{total_tests}: 输入={input_tokens} tokens, 并发={concurrency}")
                print(f"{'='*80}\n")
                await self.emit_log(
                    "info",
                    f"矩阵测试点 {current_test}/{total_tests}: 输入={input_tokens} tokens, 并发={concurrency}",
                )

                # 备份配置
                config_snapshot = {
                    'input_tokens': self.args.input_tokens,
                    'concurrency': self.args.concurrency,
                    'duration_sec': self.args.duration_sec,
                }

                self.args.input_tokens = input_tokens
                self.args.concurrency = concurrency
                self.args.duration_sec = self.args.matrix_duration_sec

                # 重新构建 prompt
                print(f"[*] 正在构建 {input_tokens} token 输入 prompt...", flush=True)
                self.prompt = self.prompt_factory.build_prompt(input_tokens)
                self.actual_input_tokens = self.estimator.count(self.prompt)
                print(f"[*] Prompt 构建完成，实际 token 数: {self.actual_input_tokens}", flush=True)

                # 清空之前的结果
                self.results = []
                self.request_counter = 0

                # 运行单次测试
                summary = await self.run()

                # 添加矩阵标识
                summary['matrix_config'] = {
                    'input_tokens': input_tokens,
                    'concurrency': concurrency,
                    'test_index': current_test,
                    'total_tests': total_tests,
                }

                results_matrix.append(summary)

                # 恢复配置
                self.args.input_tokens = config_snapshot['input_tokens']
                self.args.concurrency = config_snapshot['concurrency']
                self.args.duration_sec = config_snapshot['duration_sec']

                # 测试点之间的冷却时间
                if current_test < total_tests and not self.should_stop():
                    cooldown = 10
                    print(f"\n[*] 冷却 {cooldown} 秒后开始下一个测试点...\n")
                    await self.emit_log("info", f"冷却 {cooldown} 秒后开始下一个测试点")
                    await asyncio.sleep(cooldown)

            if self.should_stop():
                break

        print(f"\n{'='*80}")
        print(f"[*] 矩阵测试完成！共完成 {len(results_matrix)}/{total_tests} 个测试点")
        print(f"{'='*80}\n")
        await self.emit_log("info", f"矩阵测试结束，已完成 {len(results_matrix)}/{total_tests} 个测试点")

        return results_matrix

    def percentile(self, values: List[float], p: float) -> Optional[float]:
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        values = sorted(values)
        k = (len(values) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return values[int(k)]
        d0 = values[f] * (c - k)
        d1 = values[c] * (k - f)
        return d0 + d1

    @staticmethod
    def _calc_throughput_metrics(
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        wall_time: float
    ) -> dict:
        """计算吞吐量指标（TPM 和 TPS）"""
        if wall_time <= 0:
            return {
                "input_tpm": 0.0, "output_tpm": 0.0, "total_tpm": 0.0,
                "input_tps": 0.0, "output_tps": 0.0, "total_tps": 0.0,
            }

        return {
            "input_tpm": round(input_tokens * 60 / wall_time, 2),
            "output_tpm": round(output_tokens * 60 / wall_time, 2),
            "total_tpm": round(total_tokens * 60 / wall_time, 2),
            "input_tps": round(input_tokens / wall_time, 2),
            "output_tps": round(output_tokens / wall_time, 2),
            "total_tps": round(total_tokens / wall_time, 2),
        }

    def _calc_percentile_metrics(
        self,
        values: List[float],
        prefix: str
    ) -> dict:
        """计算百分位数指标（P50/P90/P95/P99）"""
        if not values:
            return {
                f"{prefix}_avg": None,
                f"{prefix}_p50": None,
                f"{prefix}_p90": None,
                f"{prefix}_p95": None,
                f"{prefix}_p99": None,
            }

        return {
            f"{prefix}_avg": round(statistics.mean(values), 4),
            f"{prefix}_p50": round(self.percentile(values, 0.50), 4),
            f"{prefix}_p90": round(self.percentile(values, 0.90), 4),
            f"{prefix}_p95": round(self.percentile(values, 0.95), 4),
            f"{prefix}_p99": round(self.percentile(values, 0.99), 4),
        }

    def summarize(self) -> Dict[str, Any]:
        all_results = self.results
        success = [r for r in all_results if r.ok]
        failed = [r for r in all_results if not r.ok]

        # 现有统计
        latencies = [r.latency_sec for r in success]
        wall_time = self.args.duration_sec
        total_input_tokens = sum(r.input_tokens for r in success)
        total_output_tokens = sum(r.output_tokens for r in success)
        total_tokens = sum(r.total_tokens for r in success)

        # 新增：TTFT 统计
        ttfts = [r.ttft_sec for r in success if r.ttft_sec is not None]
        ttft_available = len(ttfts) > 0

        # 新增：Decode 时间统计
        decode_times = []
        if ttft_available:
            decode_times = [
                r.latency_sec - r.ttft_sec
                for r in success
                if r.ttft_sec is not None
            ]

        error_counts = Counter(r.error_type or "UNKNOWN" for r in failed)
        status_counts = Counter(str(r.status) for r in all_results)

        summary = {
            "config": {
                "api_protocol": self.api_protocol(),
                "anthropic_version": getattr(self.args, "anthropic_version", "2023-06-01"),
                "base_url": self.args.base_url,
                "endpoint": self.args.endpoint,
                "model": self.args.model,
                "concurrency": self.args.concurrency,
                "duration_sec": self.args.duration_sec,
                "input_tokens_target": self.args.input_tokens,
                "input_tokens_actual": self.actual_input_tokens,
                "max_output_tokens": self.args.max_output_tokens,
                "timeout_sec": self.args.timeout_sec,
                "warmup_requests": self.args.warmup_requests,
                "enable_stream": self.args.enable_stream,
            },
            "results": {
                # 现有指标
                "total_requests": len(all_results),
                "successful_requests": len(success),
                "failed_requests": len(failed),
                "success_rate": round(len(success) / len(all_results), 4) if all_results else 0.0,

                # 吞吐量指标
                "qps": round(len(success) / wall_time, 4) if wall_time > 0 else 0.0,
                "rpm": round(len(success) * 60 / wall_time, 4) if wall_time > 0 else 0.0,

                # TPM 和 TPS 指标
                **self._calc_throughput_metrics(
                    total_input_tokens,
                    total_output_tokens,
                    total_tokens,
                    wall_time
                ),

                # 延迟指标
                **self._calc_percentile_metrics(latencies, "latency_sec"),

                # TTFT 指标
                **self._calc_percentile_metrics(ttfts, "ttft_sec"),
                "ttft_samples": len(ttfts),

                # Decode 时间指标
                **self._calc_percentile_metrics(decode_times, "decode_sec"),

                # 现有指标
                "status_counts": dict(status_counts),
                "error_counts": dict(error_counts),
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
            },
        }
        return summary


def _aggregate_by_time_window(details: List[RequestResult], window_sec: float = 1.0) -> List[Dict[str, Any]]:
    """按时间窗口聚合指标"""
    if not details:
        return []

    success_details = [d for d in details if d.ok]
    if not success_details:
        return []

    start_time = min(d.started_at for d in success_details)
    end_time = max(d.ended_at for d in success_details)

    buckets = []
    current = start_time

    while current < end_time:
        bucket_end = current + window_sec
        window_requests = [d for d in success_details if current <= d.started_at < bucket_end]

        if window_requests:
            total_tokens = sum(d.total_tokens for d in window_requests)
            ttfts = [d.ttft_sec for d in window_requests if d.ttft_sec is not None]

            buckets.append({
                'timestamp': current,
                'qps': len(window_requests) / window_sec,
                'tpm': total_tokens / window_sec * 60,
                'avg_ttft': statistics.mean(ttfts) if ttfts else None,
            })

        current = bucket_end

    return buckets


def _calculate_histogram(values: List[float], bins: int = 50) -> Dict[str, List]:
    """计算直方图数据"""
    if not values:
        return {'bins': [], 'counts': []}

    min_val, max_val = min(values), max(values)
    if min_val == max_val:
        return {'bins': [min_val], 'counts': [len(values)]}

    bin_width = (max_val - min_val) / bins
    bin_edges = [min_val + i * bin_width for i in range(bins + 1)]
    counts = [0] * bins

    for val in values:
        bin_idx = min(int((val - min_val) / bin_width), bins - 1)
        counts[bin_idx] += 1

    bin_centers = [(bin_edges[i] + bin_edges[i + 1]) / 2 for i in range(bins)]
    return {'bins': bin_centers, 'counts': counts}


def _analyze_metric(
    value: Optional[float],
    thresholds: List[tuple[float, str]],
    metric_name: str
) -> Optional[str]:
    """
    根据阈值分析指标并返回结论

    Args:
        value: 指标值
        thresholds: [(阈值, 结论), ...] 按降序排列
        metric_name: 指标名称（用于日志）

    Returns:
        分析结论字符串，如果 value 为 None 则返回 None
    """
    if value is None:
        return None

    for threshold, message in thresholds:
        if value > threshold:
            return message

    # 默认结论（所有阈值都未触发）
    return thresholds[-1][1] if thresholds else None


def render_markdown_report(summary: Dict[str, Any]) -> str:
    cfg = summary["config"]
    res = summary["results"]
    conclusion = []

    if res["success_rate"] >= 0.99:
        conclusion.append("服务在当前压测参数下整体稳定，成功率达到目标水平。")
    elif res["success_rate"] >= 0.95:
        conclusion.append("服务基本可用，但存在一定比例失败，需要定位限流、超时或网关瓶颈。")
    else:
        conclusion.append("服务在当前压测参数下不稳定，建议优先处理容量、限流和请求超时问题。")

    # 延迟分析
    latency_conclusion = _analyze_metric(
        res.get("latency_sec_p95"),
        [
            (60, "P95 延迟较高，长上下文推理或排队延迟可能是主要瓶颈。"),
            (20, "P95 延迟偏高，建议结合服务端队列时长、prefill 时间和 decode 时间继续拆解。"),
            (0, "延迟表现较平稳，尾延迟可接受。"),
        ],
        "latency_p95"
    )
    if latency_conclusion:
        conclusion.append(latency_conclusion)

    # TTFT 分析
    ttft_conclusion = _analyze_metric(
        res.get("ttft_sec_p95"),
        [
            (10, "TTFT P95 超过 10 秒，Prefill 阶段存在严重瓶颈，建议检查模型加载、KV cache 分配和批处理策略。"),
            (5, "TTFT P95 偏高，长上下文 Prefill 可能是主要瓶颈。"),
            (0, "TTFT 表现良好，Prefill 阶段无明显瓶颈。"),
        ],
        "ttft_p95"
    )
    if ttft_conclusion:
        conclusion.append(ttft_conclusion)

    report = f"""# LLM API 压测报告

## 1. 测试目标
验证 LLM API 在高并发、长上下文条件下的稳定性、吞吐与延迟表现，重点观察：
- 是否能稳定承载长上下文 prefill 压力
- 在高并发下的成功率、尾延迟和错误分布
- 输入 TPM / 总 TPM 是否达到预期容量目标
- TTFT（首 token 时间）和 Decode 时间的分布特征

## 2. 测试配置
- 协议类型: **{cfg.get('api_protocol', 'openai')}**
- Base URL: `{cfg['base_url']}`
- Endpoint: `{cfg['endpoint']}`
- Model: `{cfg['model']}`
- 并发数: **{cfg['concurrency']}**
- 测试时长: **{cfg['duration_sec']} s**
- 目标输入 tokens: **{cfg['input_tokens_target']}**
- 实际输入 tokens: **{cfg['input_tokens_actual']}**
- 最大输出 tokens: **{cfg['max_output_tokens']}**
- 单请求超时: **{cfg['timeout_sec']} s**
- 预热请求数: **{cfg['warmup_requests']}**
- 流式模式: **{'启用' if cfg.get('enable_stream') else '禁用'}**

## 3. 核心结果

### 3.1 吞吐量指标
- 总请求数: **{res['total_requests']}**
- 成功请求数: **{res['successful_requests']}**
- 失败请求数: **{res['failed_requests']}**
- 成功率: **{res['success_rate'] * 100:.2f}%**
- QPS: **{res['qps']}**
- RPM: **{res['rpm']}**

### 3.2 Token 吞吐量
| 指标 | TPM | TPS |
|------|-----|-----|
| 输入 | {res['input_tpm']:,.0f} | {res['input_tps']:,.2f} |
| 输出 | {res['output_tpm']:,.0f} | {res['output_tps']:,.2f} |
| 总计 | {res['total_tpm']:,.0f} | {res['total_tps']:,.2f} |

### 3.3 延迟分布（秒）
| 指标 | 平均值 | P50 | P90 | P95 | P99 |
|------|--------|-----|-----|-----|-----|
| 总延迟 | {res['latency_sec_avg'] or 'N/A'} | {res['latency_sec_p50'] or 'N/A'} | {res['latency_sec_p90'] or 'N/A'} | {res['latency_sec_p95'] or 'N/A'} | {res['latency_sec_p99'] or 'N/A'} |
| TTFT | {res['ttft_sec_avg'] or 'N/A'} | {res['ttft_sec_p50'] or 'N/A'} | {res['ttft_sec_p90'] or 'N/A'} | {res['ttft_sec_p95'] or 'N/A'} | {res['ttft_sec_p99'] or 'N/A'} |
| Decode | {res['decode_sec_avg'] or 'N/A'} | {res['decode_sec_p50'] or 'N/A'} | {res['decode_sec_p90'] or 'N/A'} | {res['decode_sec_p95'] or 'N/A'} | {res['decode_sec_p99'] or 'N/A'} |

**说明**：
- TTFT（Time To First Token）：从请求发送到接收首个 token 的时间，反映 Prefill 阶段性能
- Decode：从首个 token 到完整响应的时间，反映生成阶段性能
- TTFT 样本数：{res.get('ttft_samples', 0)}（仅流式模式可用）

## 4. 状态码分布
```json
{json.dumps(res['status_counts'], ensure_ascii=False, indent=2)}
```

## 5. 错误分布
```json
{json.dumps(res['error_counts'], ensure_ascii=False, indent=2)}
```

## 6. 结果解读
{" ".join(conclusion)}

## 7. 性能瓶颈分析

### 7.1 延迟构成分析
"""

    # 添加延迟构成分析
    if res.get('ttft_sec_avg') and res.get('decode_sec_avg'):
        ttft_ratio = res['ttft_sec_avg'] / res['latency_sec_avg'] * 100 if res['latency_sec_avg'] else 0
        decode_ratio = res['decode_sec_avg'] / res['latency_sec_avg'] * 100 if res['latency_sec_avg'] else 0
        report += f"""
- TTFT 占总延迟比例: **{ttft_ratio:.1f}%**
- Decode 占总延迟比例: **{decode_ratio:.1f}%**

**分析**：
"""
        if ttft_ratio > 70:
            report += "- Prefill 阶段是主要瓶颈，建议优化长上下文处理、KV cache 分配策略\n"
        elif decode_ratio > 70:
            report += "- Decode 阶段是主要瓶颈，建议优化生成速度、批处理策略\n"
        else:
            report += "- Prefill 和 Decode 时间较为均衡\n"
    else:
        report += "\n**注意**：未启用流式模式，无法测量 TTFT 和 Decode 时间。建议使用 `--enable-stream` 参数重新测试。\n"

    report += f"""
### 7.2 吞吐量评估
- 峰值 Total-TPM: **{res['total_tpm']:,.0f}**（当前测试）
- 理论 Total-TPM: 取决于模型容量和硬件配置

## 8. 结论与建议
1. **先确认模型上下文窗口**：并非所有模型都支持超长输入；若模型上下文上限低于测试值，失败并不代表服务容量不足。
2. **重点拆分延迟结构**：建议服务端增加 queue time、prefill time、decode time、first token time 指标。
3. **区分限流与容量瓶颈**：若 429 较多，优先调整配额；若 5xx/超时较多，更可能是推理实例瓶颈。
4. **逐级压测更有价值**：建议补充并发 50 / 100 / 150 / 200 的阶梯测试，找出拐点。
5. **长上下文建议单独评估**：超长 prompt 主要施压 prefill 吞吐，不等价于短 prompt 业务场景。
6. **启用流式模式测量 TTFT**：使用 `--enable-stream` 参数可获得更详细的性能分析数据。

## 9. 复现实验命令
```bash
python glm_tpm_test.py \\
  --api-protocol {cfg.get('api_protocol', 'openai')} \\
  --base-url {cfg['base_url']} \\
  --api-key '$API_KEY' \\
  --model {cfg['model']} \\
  --endpoint {cfg['endpoint']} \\
  --concurrency {cfg['concurrency']} \\
  --duration-sec {cfg['duration_sec']} \\
  --input-tokens {cfg['input_tokens_actual']} \\
  --max-output-tokens {cfg['max_output_tokens']} \\
  --timeout-sec {cfg['timeout_sec']} \\
  --enable-stream \\
  --output-dir ./results
```
"""
    return report


def render_html_report(summary: Dict[str, Any], details: List[RequestResult]) -> str:
    """生成交互式 HTML 可视化报告"""
    cfg = summary["config"]
    res = summary["results"]

    # 准备时间序列数据
    success_details = [d for d in details if d.ok]
    if not success_details:
        time_series_data = []
    else:
        start_time = min(d.started_at for d in success_details)
        time_series_data = []
        for d in success_details:
            time_offset = d.started_at - start_time
            time_series_data.append({
                'time': round(time_offset, 2),
                'latency': round(d.latency_sec, 4),
                'ttft': round(d.ttft_sec, 4) if d.ttft_sec else None,
                'decode': round(d.latency_sec - d.ttft_sec, 4) if d.ttft_sec else None,
            })

    # 准备吞吐量趋势数据
    throughput_data = _aggregate_by_time_window(details, window_sec=2.0)

    # 准备延迟分布数据
    latencies = [d.latency_sec for d in success_details]
    latency_hist = _calculate_histogram(latencies, bins=50)

    ttfts = [d.ttft_sec for d in success_details if d.ttft_sec is not None]
    ttft_hist = _calculate_histogram(ttfts, bins=50)

    # 准备成功率和错误分布数据
    total_requests = res['total_requests']
    success_count = res['successful_requests']
    failed_count = res['failed_requests']
    error_counts = res['error_counts']

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM API 压测报告 - {cfg['model']}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 p-8">
    <div class="max-w-7xl mx-auto">
        <h1 class="text-4xl font-bold text-gray-900 mb-2">LLM API 压测报告</h1>
        <p class="text-gray-600 mb-8">模型: {cfg['model']} | 并发: {cfg['concurrency']} | 时长: {cfg['duration_sec']}s</p>

        <!-- 核心指标卡片 -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">成功率</div>
                <div class="text-3xl font-bold text-green-600">{res['success_rate']*100:.2f}%</div>
                <div class="text-xs text-gray-500 mt-1">{success_count}/{total_requests} 请求</div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">QPS / RPM</div>
                <div class="text-3xl font-bold text-blue-600">{res['qps']:.1f}</div>
                <div class="text-xs text-gray-500 mt-1">RPM: {res['rpm']:.1f}</div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">Total TPM</div>
                <div class="text-3xl font-bold text-purple-600">{res['total_tpm']:,.0f}</div>
                <div class="text-xs text-gray-500 mt-1">TPS: {res['total_tps']:,.1f}</div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <div class="text-sm text-gray-600 mb-1">延迟 P95</div>
                <div class="text-3xl font-bold text-orange-600">{res.get('latency_sec_p95', 0):.2f}s</div>
                <div class="text-xs text-gray-500 mt-1">平均: {res.get('latency_sec_avg', 0):.2f}s</div>
            </div>
        </div>

        <!-- 图表区域 -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">延迟时间序列</h2>
                <div id="latencyTimeline" style="width: 100%; height: 400px;"></div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">吞吐量趋势</h2>
                <div id="throughputTrend" style="width: 100%; height: 400px;"></div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">成功率与错误分布</h2>
                <div id="successRate" style="width: 100%; height: 400px;"></div>
            </div>
            <div class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">延迟分布直方图</h2>
                <div id="latencyHistogram" style="width: 100%; height: 400px;"></div>
            </div>
        </div>

        <!-- 详细统计表格 -->
        <div class="bg-white rounded-lg shadow p-6 mb-8">
            <h2 class="text-xl font-semibold mb-4">详细统计</h2>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">指标</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">平均值</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P50</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P90</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P95</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P99</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">总延迟 (s)</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_avg') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p50') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p90') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p95') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('latency_sec_p99') or 'N/A'}</td>
                        </tr>
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">TTFT (s)</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_avg') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p50') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p90') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p95') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('ttft_sec_p99') or 'N/A'}</td>
                        </tr>
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">Decode (s)</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_avg') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p50') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p90') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p95') or 'N/A'}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{res.get('decode_sec_p99') or 'N/A'}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        // 数据准备
        const timeSeriesData = {json.dumps(time_series_data, ensure_ascii=False)};
        const throughputData = {json.dumps(throughput_data, ensure_ascii=False)};
        const latencyHist = {json.dumps(latency_hist, ensure_ascii=False)};
        const ttftHist = {json.dumps(ttft_hist, ensure_ascii=False)};
        const errorCounts = {json.dumps(error_counts, ensure_ascii=False)};

        // 图表1: 延迟时间序列
        const chart1 = echarts.init(document.getElementById('latencyTimeline'));
        chart1.setOption({{
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'cross' }}
            }},
            legend: {{
                data: ['总延迟', 'TTFT', 'Decode']
            }},
            xAxis: {{
                type: 'value',
                name: '时间 (s)',
                nameLocation: 'middle',
                nameGap: 30
            }},
            yAxis: {{
                type: 'value',
                name: '延迟 (s)',
                nameLocation: 'middle',
                nameGap: 50
            }},
            series: [
                {{
                    name: '总延迟',
                    type: 'scatter',
                    data: timeSeriesData.map(d => [d.time, d.latency]),
                    symbolSize: 4,
                    itemStyle: {{ color: '#3b82f6' }}
                }},
                {{
                    name: 'TTFT',
                    type: 'scatter',
                    data: timeSeriesData.filter(d => d.ttft !== null).map(d => [d.time, d.ttft]),
                    symbolSize: 4,
                    itemStyle: {{ color: '#10b981' }}
                }},
                {{
                    name: 'Decode',
                    type: 'scatter',
                    data: timeSeriesData.filter(d => d.decode !== null).map(d => [d.time, d.decode]),
                    symbolSize: 4,
                    itemStyle: {{ color: '#f59e0b' }}
                }}
            ]
        }});

        // 图表2: 吞吐量趋势
        const chart2 = echarts.init(document.getElementById('throughputTrend'));
        chart2.setOption({{
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'cross' }}
            }},
            legend: {{
                data: ['QPS', 'TPM']
            }},
            xAxis: {{
                type: 'value',
                name: '时间 (s)',
                nameLocation: 'middle',
                nameGap: 30
            }},
            yAxis: [
                {{
                    type: 'value',
                    name: 'QPS',
                    position: 'left',
                    nameLocation: 'middle',
                    nameGap: 50
                }},
                {{
                    type: 'value',
                    name: 'TPM',
                    position: 'right',
                    nameLocation: 'middle',
                    nameGap: 50
                }}
            ],
            series: [
                {{
                    name: 'QPS',
                    type: 'line',
                    data: throughputData.map(d => [d.timestamp, d.qps]),
                    smooth: true,
                    itemStyle: {{ color: '#3b82f6' }}
                }},
                {{
                    name: 'TPM',
                    type: 'line',
                    yAxisIndex: 1,
                    data: throughputData.map(d => [d.timestamp, d.tpm]),
                    smooth: true,
                    itemStyle: {{ color: '#8b5cf6' }}
                }}
            ]
        }});

        // 图表3: 成功率与错误分布
        const chart3 = echarts.init(document.getElementById('successRate'));
        const errorData = Object.entries(errorCounts).map(([name, value]) => ({{ name, value }}));
        chart3.setOption({{
            tooltip: {{
                trigger: 'item',
                formatter: '{{b}}: {{c}} ({{d}}%)'
            }},
            legend: {{
                orient: 'vertical',
                left: 'left'
            }},
            series: [
                {{
                    name: '请求分布',
                    type: 'pie',
                    radius: '50%',
                    data: [
                        {{ value: {success_count}, name: '成功', itemStyle: {{ color: '#10b981' }} }},
                        {{ value: {failed_count}, name: '失败', itemStyle: {{ color: '#ef4444' }} }}
                    ],
                    emphasis: {{
                        itemStyle: {{
                            shadowBlur: 10,
                            shadowOffsetX: 0,
                            shadowColor: 'rgba(0, 0, 0, 0.5)'
                        }}
                    }}
                }}
            ]
        }});

        // 图表4: 延迟分布直方图
        const chart4 = echarts.init(document.getElementById('latencyHistogram'));
        const p50 = {res.get('latency_sec_p50') or 0};
        const p95 = {res.get('latency_sec_p95') or 0};
        const p99 = {res.get('latency_sec_p99') or 0};

        chart4.setOption({{
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'shadow' }}
            }},
            xAxis: {{
                type: 'value',
                name: '延迟 (s)',
                nameLocation: 'middle',
                nameGap: 30
            }},
            yAxis: {{
                type: 'value',
                name: '请求数',
                nameLocation: 'middle',
                nameGap: 50
            }},
            series: [
                {{
                    name: '延迟分布',
                    type: 'bar',
                    data: latencyHist.bins.map((bin, i) => [bin, latencyHist.counts[i]]),
                    itemStyle: {{ color: '#3b82f6' }},
                    markLine: {{
                        data: [
                            {{ xAxis: p50, name: 'P50', lineStyle: {{ color: '#10b981' }} }},
                            {{ xAxis: p95, name: 'P95', lineStyle: {{ color: '#f59e0b' }} }},
                            {{ xAxis: p99, name: 'P99', lineStyle: {{ color: '#ef4444' }} }}
                        ],
                        label: {{
                            formatter: '{{b}}: {{c}}s'
                        }}
                    }}
                }}
            ]
        }});

        // 响应式调整
        window.addEventListener('resize', () => {{
            chart1.resize();
            chart2.resize();
            chart3.resize();
            chart4.resize();
        }});
    </script>
</body>
</html>
"""
    return html


def render_matrix_report(results_matrix: list[Dict[str, Any]]) -> str:
    """生成矩阵测试的 Markdown 报告"""

    if not results_matrix:
        return "# 矩阵测试报告\n\n无测试数据。"

    first_result = results_matrix[0]
    cfg = first_result["config"]

    report = f"""# LLM API 矩阵压测报告

## 1. 测试概览
- Base URL: `{cfg['base_url']}`
- Model: `{cfg['model']}`
- 测试点数量: **{len(results_matrix)}**
- 每个测试点持续时间: **{first_result['config']['duration_sec']} 秒**
- 流式模式: **{'启用' if cfg.get('enable_stream') else '禁用'}**

## 2. 测试矩阵结果

### 2.1 吞吐量矩阵（RPM）

| 输入 Tokens \\ 并发 |"""

    # 提取所有唯一的输入规模和并发级别
    input_tokens_set = sorted(set(r['matrix_config']['input_tokens'] for r in results_matrix))
    concurrency_set = sorted(set(r['matrix_config']['concurrency'] for r in results_matrix))

    # 构建表头
    for conc in concurrency_set:
        report += f" {conc} |"
    report += "\n|" + "---|" * (len(concurrency_set) + 1) + "\n"

    # 构建表格内容
    for input_tokens in input_tokens_set:
        report += f"| {input_tokens:,} |"
        for conc in concurrency_set:
            # 查找对应的测试结果
            result = next((r for r in results_matrix
                          if r['matrix_config']['input_tokens'] == input_tokens
                          and r['matrix_config']['concurrency'] == conc), None)
            if result:
                rpm = result['results']['rpm']
                report += f" {rpm:.1f} |"
            else:
                report += " N/A |"
        report += "\n"

    # TPM 矩阵
    report += "\n### 2.2 Total TPM 矩阵\n\n| 输入 Tokens \\ 并发 |"
    for conc in concurrency_set:
        report += f" {conc} |"
    report += "\n|" + "---|" * (len(concurrency_set) + 1) + "\n"

    for input_tokens in input_tokens_set:
        report += f"| {input_tokens:,} |"
        for conc in concurrency_set:
            result = next((r for r in results_matrix
                          if r['matrix_config']['input_tokens'] == input_tokens
                          and r['matrix_config']['concurrency'] == conc), None)
            if result:
                tpm = result['results']['total_tpm']
                report += f" {tpm:,.0f} |"
            else:
                report += " N/A |"
        report += "\n"

    # TTFT 矩阵
    report += "\n### 2.3 TTFT P95 矩阵（秒）\n\n| 输入 Tokens \\ 并发 |"
    for conc in concurrency_set:
        report += f" {conc} |"
    report += "\n|" + "---|" * (len(concurrency_set) + 1) + "\n"

    for input_tokens in input_tokens_set:
        report += f"| {input_tokens:,} |"
        for conc in concurrency_set:
            result = next((r for r in results_matrix
                          if r['matrix_config']['input_tokens'] == input_tokens
                          and r['matrix_config']['concurrency'] == conc), None)
            if result:
                ttft_p95 = result['results'].get('ttft_sec_p95')
                if ttft_p95:
                    report += f" {ttft_p95:.2f} |"
                else:
                    report += " N/A |"
            else:
                report += " N/A |"
        report += "\n"

    # 延迟 P95 矩阵
    report += "\n### 2.4 总延迟 P95 矩阵（秒）\n\n| 输入 Tokens \\ 并发 |"
    for conc in concurrency_set:
        report += f" {conc} |"
    report += "\n|" + "---|" * (len(concurrency_set) + 1) + "\n"

    for input_tokens in input_tokens_set:
        report += f"| {input_tokens:,} |"
        for conc in concurrency_set:
            result = next((r for r in results_matrix
                          if r['matrix_config']['input_tokens'] == input_tokens
                          and r['matrix_config']['concurrency'] == conc), None)
            if result:
                latency_p95 = result['results'].get('latency_sec_p95')
                if latency_p95:
                    report += f" {latency_p95:.2f} |"
                else:
                    report += " N/A |"
            else:
                report += " N/A |"
        report += "\n"

    # 成功率矩阵
    report += "\n### 2.5 成功率矩阵（%）\n\n| 输入 Tokens \\ 并发 |"
    for conc in concurrency_set:
        report += f" {conc} |"
    report += "\n|" + "---|" * (len(concurrency_set) + 1) + "\n"

    for input_tokens in input_tokens_set:
        report += f"| {input_tokens:,} |"
        for conc in concurrency_set:
            result = next((r for r in results_matrix
                          if r['matrix_config']['input_tokens'] == input_tokens
                          and r['matrix_config']['concurrency'] == conc), None)
            if result:
                success_rate = result['results']['success_rate'] * 100
                report += f" {success_rate:.2f} |"
            else:
                report += " N/A |"
        report += "\n"

    # 分析和建议
    report += """
## 3. 矩阵分析

### 3.1 性能趋势
- **输入规模影响**：观察同一并发下，不同输入规模对 TTFT 和吞吐量的影响
- **并发影响**：观察同一输入规模下，不同并发对延迟和成功率的影响
- **最优配置**：找出成功率高、延迟低、吞吐量大的最优配置点

### 3.2 瓶颈识别
- 如果 TTFT 随输入规模线性增长，说明 Prefill 性能稳定
- 如果高并发下成功率下降，说明存在容量瓶颈或限流
- 如果延迟 P95 显著高于 P50，说明存在排队或资源竞争

### 3.3 容量规划建议
1. 根据业务场景的输入规模分布，选择合适的并发配置
2. 预留 20-30% 的容量余量应对突发流量
3. 监控成功率低于 99% 的配置点，避免在生产环境使用

## 4. 复现命令
```bash
python glm_tpm_test.py \\
  --base-url {cfg['base_url']} \\
  --api-key '$API_KEY' \\
  --model {cfg['model']} \\
  --matrix-mode \\
  --input-tokens-list '200,2000,20000,120000' \\
  --concurrency-list '120,240,480' \\
  --matrix-duration-sec 60 \\
  --enable-stream \\
  --output-dir ./results
```
"""

    return report


def generate_matrix_csv(results_matrix: list[Dict[str, Any]]) -> str:
    """生成矩阵测试的 CSV 格式数据"""

    csv_lines = [
        "input_tokens,concurrency,rpm,qps,input_tpm,output_tpm,total_tpm,input_tps,output_tps,total_tps,"
        "success_rate,latency_avg,latency_p50,latency_p95,latency_p99,"
        "ttft_avg,ttft_p50,ttft_p95,ttft_p99,decode_avg,decode_p95"
    ]

    for result in results_matrix:
        matrix_cfg = result['matrix_config']
        res = result['results']

        line = f"{matrix_cfg['input_tokens']},{matrix_cfg['concurrency']},"
        line += f"{res['rpm']},{res['qps']},"
        line += f"{res['input_tpm']},{res['output_tpm']},{res['total_tpm']},"
        line += f"{res['input_tps']},{res['output_tps']},{res['total_tps']},"
        line += f"{res['success_rate']},"
        line += f"{res.get('latency_sec_avg') or ''},"
        line += f"{res.get('latency_sec_p50') or ''},"
        line += f"{res.get('latency_sec_p95') or ''},"
        line += f"{res.get('latency_sec_p99') or ''},"
        line += f"{res.get('ttft_sec_avg') or ''},"
        line += f"{res.get('ttft_sec_p50') or ''},"
        line += f"{res.get('ttft_sec_p95') or ''},"
        line += f"{res.get('ttft_sec_p99') or ''},"
        line += f"{res.get('decode_sec_avg') or ''},"
        line += f"{res.get('decode_sec_p95') or ''}"

        csv_lines.append(line)

    return "\n".join(csv_lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM API 压测脚本（OpenAI-compatible / Anthropic Messages / Gemini）")
    parser.add_argument("--api-protocol", choices=list(PROTOCOL_SPECS.keys()), default="openai", help="接口协议类型")
    parser.add_argument("--anthropic-version", default="2023-06-01", help="Anthropic API 版本请求头")
    parser.add_argument("--base-url", default="https://api.wenwen-ai.com", help="例如 https://api.wenwen-ai.com")
    parser.add_argument("--api-key", default="sk-G5JY02Ovu0HN6aEXc8wXfObOL7qVT30ulzNJewmVrwdDtovD", help="API Key")
    parser.add_argument("--model", default="glm-5.1", help="模型名")
    parser.add_argument("--endpoint", default="/chat/completions", help="/chat/completions 或 /responses")
    parser.add_argument("--concurrency", type=int, default=500)
    parser.add_argument("--duration-sec", type=int, default=300)
    parser.add_argument("--input-tokens", type=int, default=60000)
    parser.add_argument("--max-output-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-sec", type=int, default=600)
    parser.add_argument("--connect-timeout-sec", type=int, default=30)
    parser.add_argument("--warmup-requests", type=int, default=5)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-base", type=float, default=1.0)
    parser.add_argument("--retry-backoff-max", type=float, default=8.0)
    parser.add_argument("--think-time-ms", type=int, default=0)
    parser.add_argument("--output-dir", default="./results")
    parser.add_argument("--enable-stream", action="store_true", default=True, help="启用流式响应以测量 TTFT")
    parser.add_argument("--matrix-mode", action="store_true", default=False, help="启用矩阵测试模式")
    parser.add_argument("--input-tokens-list", type=str, default="60000,80000,100000", help="输入 tokens 列表，逗号分隔")
    parser.add_argument("--concurrency-list", type=str, default="300,500,700", help="并发数列表，逗号分隔")
    parser.add_argument("--matrix-duration-sec", type=int, default=300, help="矩阵模式下每个测试点的持续时间（秒）")
    return parser.parse_args()


def ensure_output_dir(path: str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def async_main() -> int:
    args = parse_args()
    out_dir = ensure_output_dir(args.output_dir)

    tester = LoadTester(args)

    # 矩阵测试模式
    if args.matrix_mode:
        if not args.input_tokens_list or not args.concurrency_list:
            print("错误：矩阵模式需要指定 --input-tokens-list 和 --concurrency-list", file=sys.stderr)
            return 1

        results_matrix = await tester.run_matrix()

        ts = time.strftime("%Y%m%d_%H%M%S")
        matrix_summary_path = out_dir / f"matrix_summary_{ts}.json"
        matrix_report_path = out_dir / f"matrix_report_{ts}.md"
        matrix_csv_path = out_dir / f"matrix_results_{ts}.csv"

        # 保存矩阵汇总 JSON
        with matrix_summary_path.open("w", encoding="utf-8") as f:
            json.dump(results_matrix, f, ensure_ascii=False, indent=2)

        # 生成矩阵报告
        matrix_report_md = render_matrix_report(results_matrix)
        with matrix_report_path.open("w", encoding="utf-8") as f:
            f.write(matrix_report_md)

        # 生成 CSV
        matrix_csv = generate_matrix_csv(results_matrix)
        with matrix_csv_path.open("w", encoding="utf-8") as f:
            f.write(matrix_csv)

        print(json.dumps({
            "matrix_summary_file": str(matrix_summary_path),
            "matrix_report_file": str(matrix_report_path),
            "matrix_csv_file": str(matrix_csv_path),
            "test_points": len(results_matrix),
        }, ensure_ascii=False, indent=2))

        return 0

    # 单点测试模式（原有逻辑）
    summary = await tester.run()

    ts = time.strftime("%Y%m%d_%H%M%S")
    summary_path = out_dir / f"summary_{ts}.json"
    detail_path = out_dir / f"details_{ts}.jsonl"
    report_path = out_dir / f"report_{ts}.md"

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with detail_path.open("w", encoding="utf-8") as f:
        for item in tester.results:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    report_md = render_markdown_report(summary)
    with report_path.open("w", encoding="utf-8") as f:
        f.write(report_md)

    # 生成 HTML 报告
    html_report = render_html_report(summary, tester.results)
    html_path = out_dir / f"report_{ts}.html"
    with html_path.open("w", encoding="utf-8") as f:
        f.write(html_report)

    print(json.dumps({
        "summary_file": str(summary_path),
        "details_file": str(detail_path),
        "report_file": str(report_path),
        "html_report_file": str(html_path),
        "summary": summary,
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
