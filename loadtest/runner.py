from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections import deque
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp

from .config import LoadTestConfig
from .executor import RequestExecutor
from .metrics import percentile, percentile_metrics, throughput_metrics
from .models import RequestResult
from .prompt import PromptFactory, TokenEstimator
from .protocols import build_headers, build_payload, build_url, extract_protocol_error, extract_tokens, protocol_spec
from .streaming import SseStreamParser
from .summary import MetricsAccumulator

ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]
LogCallback = Callable[[str, str], Awaitable[None] | None]


class LoadTestRunner:
    def __init__(
        self,
        args: argparse.Namespace | LoadTestConfig | dict[str, Any],
        progress_callback: Optional[ProgressCallback] = None,
        stop_event: Optional[asyncio.Event] = None,
        log_callback: Optional[LogCallback] = None,
    ):
        self.config = LoadTestConfig.coerce(args)
        self.args = self.config
        self.progress_callback = progress_callback
        self.stop_event = stop_event
        self.log_callback = log_callback
        self.estimator = TokenEstimator(self.config.model)
        self.prompt_factory = PromptFactory(self.estimator)
        print(f"[*] 正在构建 {self.config.input_tokens} token 输入 prompt...", flush=True)
        self.prompt = self.prompt_factory.build_prompt(self.config.input_tokens)
        self.actual_input_tokens = self.estimator.count(self.prompt)
        print(f"[*] Prompt 构建完成，实际 token 数: {self.actual_input_tokens}", flush=True)
        self.stream_parser = SseStreamParser()
        self.executor = self._create_executor()
        self.results: List[RequestResult] = []
        self.metrics_accumulator = MetricsAccumulator()
        self.stop_at = 0.0
        self.request_counter = 0
        self.counter_lock = asyncio.Lock()
        self.last_progress_emit_at = 0.0
        self.test_start_time = 0.0
        self.test_start_wall_time = 0.0
        self._success_count = 0
        self._failure_count = 0
        self._success_token_count = 0
        self._success_latency_window: deque[float] = deque(maxlen=10)

    def _create_executor(self) -> RequestExecutor:
        return RequestExecutor(
            self.config,
            prompt=self.prompt,
            actual_input_tokens=self.actual_input_tokens,
            backoff=self.backoff,
            stream_parser=self.stream_parser,
        )

    def _refresh_executor(self) -> None:
        self.executor = self._create_executor()

    @staticmethod
    async def _maybe_await(value: Any) -> None:
        if asyncio.iscoroutine(value):
            await value

    def should_stop(self) -> bool:
        return bool(self.stop_event and self.stop_event.is_set())

    async def emit_log(self, level: str, message: str) -> None:
        if self.log_callback:
            await self._maybe_await(self.log_callback(level, message))

    def _record_result(self, result: RequestResult) -> None:
        self.results.append(result)
        self.metrics_accumulator.record(result)
        if result.ok:
            self._success_count += 1
            self._success_token_count += result.total_tokens
            self._success_latency_window.append(result.latency_sec)
        else:
            self._failure_count += 1

    async def emit_progress(self, force: bool = False) -> None:
        if not self.progress_callback:
            return
        now = time.time()
        total = len(self.results)
        if not force and total % 10 != 0 and now - self.last_progress_emit_at < 2:
            return
        start_time = self.test_start_wall_time or self.test_start_time
        elapsed = max(0.001, now - start_time) if start_time else 0.001
        recent_latency = statistics.mean(self._success_latency_window) if self._success_latency_window else 0.0
        self.last_progress_emit_at = now
        await self._maybe_await(self.progress_callback({
            "completed_requests": total,
            "successful_requests": self._success_count,
            "failed_requests": self._failure_count,
            "success_rate": round(self._success_count / total, 4) if total else 0.0,
            "current_qps": round(self._success_count / elapsed, 4),
            "current_rpm": round(self._success_count * 60 / elapsed, 4),
            "current_tpm": round(self._success_token_count * 60 / elapsed, 4),
            "avg_latency_sec": round(recent_latency, 4),
            "elapsed_sec": round(elapsed, 2),
        }))

    async def next_request_id(self) -> int:
        async with self.counter_lock:
            self.request_counter += 1
            return self.request_counter

    def api_protocol(self) -> str:
        return self.config.api_protocol

    def protocol_spec(self):
        return protocol_spec(self.api_protocol())

    def build_payload(self) -> Dict[str, Any]:
        return build_payload(
            self.api_protocol(),
            endpoint=self.config.endpoint,
            model=self.config.model,
            prompt=self.prompt,
            max_output_tokens=self.config.max_output_tokens,
            temperature=self.config.temperature,
            enable_stream=self.config.enable_stream,
        )

    def build_headers(self) -> Dict[str, str]:
        return build_headers(
            self.api_protocol(),
            api_key=self.config.api_key or "",
            anthropic_version=self.config.anthropic_version,
        )

    def build_url(self) -> str:
        return build_url(
            self.config.base_url,
            self.config.endpoint,
            self.api_protocol(),
            model=self.config.model,
            enable_stream=self.config.enable_stream,
        )

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
        return self.executor.create_result(
            request_id,
            started_at,
            t0,
            ok,
            status,
            ttft=ttft,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            error_type=error_type,
            error_message=error_message,
            attempt=attempt,
        )

    def backoff(self, attempt: int) -> float:
        base = min(self.config.retry_backoff_base * (2 ** (attempt - 1)), self.config.retry_backoff_max)
        jitter = random.uniform(0, base * 0.2)
        return base + jitter

    def percentile(self, values: List[float], p: float) -> Optional[float]:
        return percentile(values, p)

    @staticmethod
    def _calc_throughput_metrics(
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        wall_time: float,
    ) -> dict:
        return throughput_metrics(input_tokens, output_tokens, total_tokens, wall_time)

    def _calc_percentile_metrics(self, values: List[float], prefix: str) -> dict:
        return percentile_metrics(values, prefix)

    @staticmethod
    def _extract_tokens(usage: dict) -> tuple[int, int]:
        return extract_tokens(usage)

    @staticmethod
    def _extract_protocol_error(data: Any) -> str | None:
        return extract_protocol_error(data)

    def _parse_stream_usage(self, stream_text: str) -> tuple[int, int]:
        return self.stream_parser.parse_usage_text(stream_text)

    async def _parse_stream(self, content: aiohttp.StreamReader, t0: float) -> tuple[Optional[float], int, int, Optional[str]]:
        return await self.stream_parser.parse_stream(content, t0)

    async def send_one(self, session: aiohttp.ClientSession, request_id: int) -> RequestResult:
        return await self.executor.send_one(session, request_id)

    async def worker(self, worker_id: int, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore):
        while time.time() < self.stop_at and not self.should_stop():
            async with semaphore:
                if self.should_stop():
                    break
                req_id = await self.next_request_id()
                result = await self.send_one(session, req_id)
                self._record_result(result)
                await self.emit_progress()
                elapsed = int(time.time() - (self.stop_at - self.config.duration_sec))
                total = len(self.results)
                success = self._success_count
                current_success_rate = success / total * 100 if total > 0 else 0
                if not result.ok:
                    error_msg = result.error_message[:200] if result.error_message else "Unknown error"
                    print(f"  [{elapsed:>4}s] req#{result.request_id} FAIL({result.error_type}) status={result.status} latency={result.latency_sec:.2f}s msg={error_msg}", flush=True)
                    await self.emit_log("error", f"req#{result.request_id} FAIL({result.error_type}) status={result.status} latency={result.latency_sec:.2f}s msg={error_msg}")
                if total % 10 == 0:
                    avg_latency = statistics.mean(self._success_latency_window) if self._success_latency_window else 0
                    print(f"  [{elapsed:>4}s] 已完成={total}, 成功={success}, 成功率={current_success_rate:.1f}%, 近10次平均延迟={avg_latency:.2f}s", flush=True)
                    await self.emit_log("info", f"已完成={total}, 成功={success}, 成功率={current_success_rate:.1f}%, 近10次平均延迟={avg_latency:.2f}s")
            if self.config.think_time_ms > 0:
                await asyncio.sleep(self.config.think_time_ms / 1000.0)

    async def run(self) -> Dict[str, Any]:
        connector = aiohttp.TCPConnector(limit=0, ssl=False)
        semaphore = asyncio.Semaphore(self.config.concurrency)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.config.connect_timeout_sec)
        self.test_start_wall_time = time.time()
        self.test_start_time = self.test_start_wall_time
        self.stop_at = self.test_start_wall_time + self.config.duration_sec
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            warmup_results = []
            if self.config.warmup_requests > 0 and not self.should_stop():
                print(f"[*] 开始预热，发送 {self.config.warmup_requests} 个预热请求...", flush=True)
                await self.emit_log("info", f"开始预热，发送 {self.config.warmup_requests} 个预热请求")
                warm_tasks = []
                for _ in range(self.config.warmup_requests):
                    req_id = await self.next_request_id()
                    warm_tasks.append(self.send_one(session, req_id))
                warmup_results = await asyncio.gather(*warm_tasks, return_exceptions=False)
                for result in warmup_results:
                    self._record_result(result)
                warmup_success = sum(1 for r in warmup_results if r.ok)
                print(f"[*] 预热完成，成功 {warmup_success}/{len(warmup_results)}", flush=True)
                await self.emit_log("info", f"预热完成，成功 {warmup_success}/{len(warmup_results)}")
                if warmup_success == 0 and warmup_results:
                    first_error = warmup_results[0]
                    print(f"[!] 预热请求全部失败！第一个错误: {first_error.error_type}", flush=True)
                    print(f"[!] 错误详情: {first_error.error_message[:500]}", flush=True)
                    print(f"[!] HTTP状态码: {first_error.status}", flush=True)
                    await self.emit_log("error", f"预热请求全部失败：{first_error.error_type}")
            print(f"[*] 开始正式压测，并发={self.config.concurrency}，时长={self.config.duration_sec}s ...", flush=True)
            await self.emit_log("info", f"开始正式压测，并发={self.config.concurrency}，时长={self.config.duration_sec}s")
            await self.emit_progress(force=True)
            tasks = [asyncio.create_task(self.worker(i, session, semaphore)) for i in range(self.config.concurrency)]
            await asyncio.gather(*tasks)
        print("[*] 压测结束，正在汇总结果...", flush=True)
        await self.emit_progress(force=True)
        await self.emit_log("info", "压测结束，正在汇总结果")
        return self.summarize()

    async def run_matrix(self) -> list[Dict[str, Any]]:
        input_tokens_list = [int(x.strip()) for x in self.config.input_tokens_list.split(",")]
        concurrency_list = [int(x.strip()) for x in self.config.concurrency_list.split(",")]
        results_matrix = []
        total_tests = len(input_tokens_list) * len(concurrency_list)
        current_test = 0
        print(f"[*] 矩阵测试模式：{len(input_tokens_list)} 个输入规模 × {len(concurrency_list)} 个并发级别 = {total_tests} 个测试点")
        print(f"[*] 每个测试点持续 {self.config.matrix_duration_sec} 秒")
        await self.emit_log("info", f"矩阵测试模式：{total_tests} 个测试点，每点 {self.config.matrix_duration_sec} 秒")
        for input_tokens in input_tokens_list:
            for concurrency in concurrency_list:
                if self.should_stop():
                    await self.emit_log("warning", "矩阵测试收到停止信号，跳过剩余测试点")
                    break
                current_test += 1
                print(f"\n{'='*80}")
                print(f"[*] 测试点 {current_test}/{total_tests}: 输入={input_tokens} tokens, 并发={concurrency}")
                print(f"{'='*80}\n")
                await self.emit_log("info", f"矩阵测试点 {current_test}/{total_tests}: 输入={input_tokens} tokens, 并发={concurrency}")
                config_snapshot = {
                    "input_tokens": self.config.input_tokens,
                    "concurrency": self.config.concurrency,
                    "duration_sec": self.config.duration_sec,
                }
                self.config.input_tokens = input_tokens
                self.config.concurrency = concurrency
                self.config.duration_sec = self.config.matrix_duration_sec
                print(f"[*] 正在构建 {input_tokens} token 输入 prompt...", flush=True)
                self.prompt = self.prompt_factory.build_prompt(input_tokens)
                self.actual_input_tokens = self.estimator.count(self.prompt)
                print(f"[*] Prompt 构建完成，实际 token 数: {self.actual_input_tokens}", flush=True)
                self._refresh_executor()
                self.results = []
                self.metrics_accumulator.reset()
                self.request_counter = 0
                self._success_count = 0
                self._failure_count = 0
                self._success_token_count = 0
                self._success_latency_window.clear()
                summary = await self.run()
                summary["matrix_config"] = {
                    "input_tokens": input_tokens,
                    "concurrency": concurrency,
                    "test_index": current_test,
                    "total_tests": total_tests,
                }
                results_matrix.append(summary)
                self.config.input_tokens = config_snapshot["input_tokens"]
                self.config.concurrency = config_snapshot["concurrency"]
                self.config.duration_sec = config_snapshot["duration_sec"]
                self._refresh_executor()
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

    def summarize(self) -> Dict[str, Any]:
        return self.metrics_accumulator.build_summary(
            self.config,
            actual_input_tokens=self.actual_input_tokens,
            started_at=self.test_start_wall_time,
        )
