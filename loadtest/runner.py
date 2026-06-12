from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import random
import statistics
import time
from collections import deque
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

import aiohttp

from .config import LoadTestConfig
from .executor import RequestExecutor
from .metrics import percentile, percentile_metrics, throughput_metrics
from .models import RequestResult
from .prompt import PromptFactory, TokenEstimator
from .protocols import build_headers, build_payload, build_url, extract_protocol_error, extract_token_usage, extract_tokens, protocol_spec
from .streaming import SseStreamParser
from .summary import MetricsAccumulator, cache_hit_rate, retry_attempt_count, retry_attempt_tokens

ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]
LogCallback = Callable[[str, str], Awaitable[None] | None]
ResultCallback = Callable[[RequestResult], None]
T = TypeVar("T")
RESUME_POLICY_MISSING_OR_FAILED = "missing_or_failed"


def matrix_point_key(input_tokens: int, concurrency: int) -> str:
    return f"{int(input_tokens)}:{int(concurrency)}"


def matrix_result_key(result: dict[str, Any]) -> str | None:
    matrix_config = result.get("matrix_config") or {}
    try:
        input_tokens = int(matrix_config["input_tokens"])
        concurrency = int(matrix_config["concurrency"])
    except (KeyError, TypeError, ValueError):
        return None
    return matrix_point_key(input_tokens, concurrency)


def should_reuse_matrix_result(result: dict[str, Any], resume_policy: str = RESUME_POLICY_MISSING_OR_FAILED) -> bool:
    if resume_policy != RESUME_POLICY_MISSING_OR_FAILED:
        return False
    metrics = result.get("results") or {}
    total_requests = int(metrics.get("total_requests") or 0)
    successful_requests = int(metrics.get("successful_requests") or 0)
    success_rate = float(metrics.get("success_rate") or 0)
    return total_requests > 0 and successful_requests > 0 and success_rate > 0


class LoadTestRunner:
    def __init__(
        self,
        args: argparse.Namespace | LoadTestConfig | dict[str, Any],
        progress_callback: Optional[ProgressCallback] = None,
        stop_event: Optional[asyncio.Event] = None,
        log_callback: Optional[LogCallback] = None,
        result_callback: Optional[ResultCallback] = None,
        retain_results: bool = True,
    ):
        self.config = LoadTestConfig.coerce(args)
        self.args = self.config
        self.progress_callback = progress_callback
        self.stop_event = stop_event
        self.log_callback = log_callback
        self.result_callback = result_callback
        self.retain_results = retain_results
        self.estimator = TokenEstimator(self.config.model)
        self.prompt_factory = PromptFactory(self.estimator)
        self._prompt_cache: dict[int, tuple[str, int]] = {}
        self.prompt, self.actual_input_tokens = self._initial_prompt()
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
        self._success_cached_input_count = 0
        self._success_cache_inclusive_token_count = 0
        self._attempt_count = 0
        self._attempt_token_count = 0
        self._success_latency_window: deque[float] = deque(maxlen=10)
        self.phase = "queued"
        self.cache_warmup_completed = 0
        self.cache_warmup_successful = 0
        self.cache_warmup_failed = 0

    def _prompt_for_tokens(self, input_tokens: int) -> tuple[str, int]:
        cached = self._prompt_cache.get(input_tokens)
        if cached:
            return cached
        print(f"[*] 正在构建 {input_tokens} token 输入 prompt...", flush=True)
        prompt = self.prompt_factory.build_prompt(input_tokens)
        actual_input_tokens = self.estimator.count(prompt)
        self._prompt_cache[input_tokens] = (prompt, actual_input_tokens)
        print(f"[*] Prompt 构建完成，实际 token 数: {actual_input_tokens}", flush=True)
        return prompt, actual_input_tokens

    def _initial_prompt(self) -> tuple[str, int]:
        if self.config.prompt_source == "custom":
            prompt = self.config.custom_prompt or ""
            actual_input_tokens = self.estimator.count(prompt)
            print(f"[*] 使用自定义输入 case，字符数: {len(prompt)}，实际 token 数: {actual_input_tokens}", flush=True)
            return prompt, actual_input_tokens
        return self._prompt_for_tokens(self.config.input_tokens)

    def _create_executor(self) -> RequestExecutor:
        return RequestExecutor(
            self.config,
            prompt=self.prompt,
            actual_input_tokens=self.actual_input_tokens,
            backoff=self.backoff,
            stream_parser=self.stream_parser,
            retry_sleep=self._sleep_or_stop,
        )

    def _refresh_executor(self) -> None:
        self.executor = self._create_executor()

    @staticmethod
    async def _maybe_await(value: Any) -> None:
        if asyncio.iscoroutine(value):
            await value

    def should_stop(self) -> bool:
        return bool(self.stop_event and self.stop_event.is_set())

    def deadline_reached(self) -> bool:
        return bool(self.stop_at and time.time() >= self.stop_at)

    async def _wait_with_stop(self, awaitable: Awaitable[T]) -> tuple[bool, T | None]:
        task = asyncio.create_task(awaitable)
        wait_tasks: list[asyncio.Task[Any]] = [task]
        stop_task: asyncio.Task[Any] | None = None
        deadline_task: asyncio.Task[Any] | None = None
        try:
            if self.stop_event is not None:
                if self.stop_event.is_set():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    return False, None
                stop_task = asyncio.create_task(self.stop_event.wait())
                wait_tasks.append(stop_task)

            if self.stop_at:
                remaining = self.stop_at - time.time()
                if remaining <= 0:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    return False, None
                deadline_task = asyncio.create_task(asyncio.sleep(remaining))
                wait_tasks.append(deadline_task)

            done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                if task.cancelled():
                    return False, None
                return True, await task

            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            return False, None
        finally:
            for waiter in wait_tasks:
                if waiter is task:
                    continue
                if not waiter.done():
                    waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await waiter

    async def _sleep_or_stop(self, seconds: float) -> bool:
        if seconds <= 0:
            return True
        completed, _ = await self._wait_with_stop(asyncio.sleep(seconds))
        return completed

    async def _request_or_stop(self, session, request_id: int) -> Optional[RequestResult]:
        completed, result = await self._wait_with_stop(self.send_one(session, request_id))
        if not completed:
            return None
        return result

    async def _run_warmup_requests(
        self,
        session,
        *,
        count: int,
        label: str,
        count_as_cache_warmup: bool = False,
    ) -> list[RequestResult]:
        if count <= 0 or self.should_stop():
            return []
        print(f"[*] 开始{label}，发送 {count} 个请求...", flush=True)
        await self.emit_log("info", f"开始{label}，发送 {count} 个请求")
        if count_as_cache_warmup:
            self.phase = "cache_warmup"
            self.cache_warmup_completed = 0
            self.cache_warmup_successful = 0
            self.cache_warmup_failed = 0
            await self.emit_progress(force=True)

        tasks = []
        for _ in range(count):
            req_id = await self.next_request_id()
            tasks.append(asyncio.create_task(self._request_or_stop(session, req_id)))
        results = [result for result in await asyncio.gather(*tasks) if result is not None]
        success = sum(1 for result in results if result.ok)

        if count_as_cache_warmup:
            self.cache_warmup_completed = len(results)
            self.cache_warmup_successful = success
            self.cache_warmup_failed = len(results) - success
            await self.emit_progress(force=True)

        print(f"[*] {label}完成，成功 {success}/{len(results)}", flush=True)
        await self.emit_log("info", f"{label}完成，成功 {success}/{len(results)}")
        if success == 0 and results:
            first_error = results[0]
            print(f"[!] {label}请求全部失败！第一个错误: {first_error.error_type}", flush=True)
            print(f"[!] 错误详情: {first_error.error_message[:500]}", flush=True)
            print(f"[!] HTTP状态码: {first_error.status}", flush=True)
            await self.emit_log("error", f"{label}请求全部失败：{first_error.error_type}")
        return results

    async def emit_log(self, level: str, message: str) -> None:
        if self.log_callback:
            await self._maybe_await(self.log_callback(level, message))

    def _reset_formal_counters(self) -> None:
        self.results = []
        self.metrics_accumulator.reset()
        self.request_counter = 0
        self._success_count = 0
        self._failure_count = 0
        self._success_token_count = 0
        self._success_cached_input_count = 0
        self._success_cache_inclusive_token_count = 0
        self._attempt_count = 0
        self._attempt_token_count = 0
        self._success_latency_window.clear()
        self.last_progress_emit_at = 0.0

    def _record_result(self, result: RequestResult) -> None:
        if self.retain_results:
            self.results.append(result)
        if self.result_callback:
            self.result_callback(result)
        self.metrics_accumulator.record(result)
        attempt_count = retry_attempt_count(result)
        self._attempt_count += attempt_count
        self._attempt_token_count += retry_attempt_tokens(result)
        if result.ok:
            self._success_count += 1
            self._success_token_count += result.total_tokens
            self._success_cached_input_count += result.cached_input_tokens
            self._success_cache_inclusive_token_count += result.cache_inclusive_total_tokens or result.total_tokens
            self._success_latency_window.append(result.latency_sec)
        else:
            self._failure_count += 1

    def _cache_progress_snapshot(self, elapsed: float) -> dict[str, Any]:
        elapsed = max(0.001, elapsed)
        return {
            "current_cache_hit_tpm": round(self._success_cached_input_count * 60 / elapsed, 4),
            "current_cache_inclusive_tpm": round(self._success_cache_inclusive_token_count * 60 / elapsed, 4),
            "current_cached_input_tokens": self._success_cached_input_count,
            "current_input_tokens": self.metrics_accumulator.total_input_tokens,
            "current_cache_creation_input_tokens": self.metrics_accumulator.total_cache_creation_input_tokens,
            "current_cache_hit_rate": cache_hit_rate(
                self._success_cached_input_count,
                self.metrics_accumulator.total_cache_creation_input_tokens,
                self.metrics_accumulator.total_input_tokens,
            ),
        }

    async def emit_progress(self, force: bool = False) -> None:
        if not self.progress_callback:
            return
        now = time.time()
        total = self.metrics_accumulator.total_requests
        if not force and total % 25 != 0 and now - self.last_progress_emit_at < 3:
            return
        start_time = self.test_start_wall_time or self.test_start_time
        elapsed = max(0.001, now - start_time) if start_time else 0.001
        recent_latency = statistics.mean(self._success_latency_window) if self._success_latency_window else 0.0
        cache_progress = self._cache_progress_snapshot(elapsed)
        self.last_progress_emit_at = now
        await self._maybe_await(self.progress_callback({
            "completed_requests": total,
            "successful_requests": self._success_count,
            "failed_requests": self._failure_count,
            "success_rate": round(self._success_count / total, 4) if total else 0.0,
            "current_qps": round(self._success_count / elapsed, 4),
            "current_rpm": round(self._success_count * 60 / elapsed, 4),
            "current_tpm": round(self._success_token_count * 60 / elapsed, 4),
            **cache_progress,
            "attempt_qps": round(self._attempt_count / elapsed, 4),
            "attempt_rpm": round(self._attempt_count * 60 / elapsed, 4),
            "attempt_tpm": round(self._attempt_token_count * 60 / elapsed, 4),
            "avg_latency_sec": round(recent_latency, 4),
            "elapsed_sec": round(elapsed, 2),
            "phase": self.phase,
            "cache_test_enabled": self.config.cache_test_enabled,
            "cache_warmup_requests": self.config.cache_warmup_requests,
            "cache_warmup_completed": self.cache_warmup_completed,
            "cache_warmup_successful": self.cache_warmup_successful,
            "cache_warmup_failed": self.cache_warmup_failed,
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
        cached_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_inclusive_total_tokens: Optional[int] = None,
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
            cached_input_tokens=cached_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_inclusive_total_tokens=cache_inclusive_total_tokens,
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
    def _extract_token_usage(usage: dict):
        return extract_token_usage(usage)

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
        while not self.should_stop() and not self.deadline_reached():
            async with semaphore:
                if self.should_stop() or self.deadline_reached():
                    break
                req_id = await self.next_request_id()
                result = await self._request_or_stop(session, req_id)
                if result is None:
                    break
                self._record_result(result)
                await self.emit_progress()
                elapsed_base = self.stop_at - self.config.duration_sec if self.stop_at else self.test_start_wall_time
                elapsed = int(max(0.0, time.time() - elapsed_base))
                total = self.metrics_accumulator.total_requests
                success = self._success_count
                current_success_rate = success / total * 100 if total > 0 else 0
                if not result.ok:
                    error_msg = result.error_message[:200] if result.error_message else "Unknown error"
                    print(f"  [{elapsed:>4}s] req#{result.request_id} FAIL({result.error_type}) status={result.status} latency={result.latency_sec:.2f}s msg={error_msg}", flush=True)
                    await self.emit_log("error", f"req#{result.request_id} FAIL({result.error_type}) status={result.status} latency={result.latency_sec:.2f}s msg={error_msg}")
                if total % 50 == 0:
                    avg_latency = statistics.mean(self._success_latency_window) if self._success_latency_window else 0
                    cache_progress = self._cache_progress_snapshot(time.time() - (self.test_start_wall_time or time.time()))
                    progress_text = (
                        f"已完成={total}, 成功={success}, 成功率={current_success_rate:.1f}%, "
                        f"缓存命中率={cache_progress['current_cache_hit_rate'] * 100:.2f}%, "
                        f"缓存命中TPM={cache_progress['current_cache_hit_tpm']:.1f}, "
                        f"含缓存TPM={cache_progress['current_cache_inclusive_tpm']:.1f}, "
                        f"近10次平均延迟={avg_latency:.2f}s"
                    )
                    print(f"  [{elapsed:>4}s] {progress_text}", flush=True)
                    await self.emit_log("info", progress_text)
            if self.config.think_time_ms > 0:
                if not await self._sleep_or_stop(self.config.think_time_ms / 1000.0):
                    break

    async def run(self) -> Dict[str, Any]:
        connector = aiohttp.TCPConnector(limit=0, ssl=False)
        semaphore = asyncio.Semaphore(self.config.concurrency)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.config.connect_timeout_sec)
        self.test_start_wall_time = time.time()
        self.test_start_time = self.test_start_wall_time
        self.stop_at = 0.0
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            if self.config.warmup_requests > 0 and not self.should_stop():
                self.phase = "warmup"
                await self._run_warmup_requests(session, count=self.config.warmup_requests, label="预热")
                if self.should_stop() or self.deadline_reached():
                    await self.emit_progress(force=True)
                    await self.emit_log("warning", "收到停止信号，结束压测")
                    return self.summarize()
            cache_warmup_count = self.config.cache_warmup_requests if self.config.cache_test_enabled else 0
            if cache_warmup_count > 0 and not self.should_stop():
                await self._run_warmup_requests(
                    session,
                    count=cache_warmup_count,
                    label="缓存预热",
                    count_as_cache_warmup=True,
                )
                if self.should_stop() or self.deadline_reached():
                    await self.emit_progress(force=True)
                    await self.emit_log("warning", "收到停止信号，结束压测")
                    return self.summarize()
            self._reset_formal_counters()
            self.test_start_wall_time = time.time()
            self.test_start_time = self.test_start_wall_time
            self.stop_at = self.test_start_wall_time + self.config.duration_sec
            self.phase = "load"
            print(f"[*] 开始正式压测，并发={self.config.concurrency}，时长={self.config.duration_sec}s ...", flush=True)
            await self.emit_log("info", f"开始正式压测，并发={self.config.concurrency}，时长={self.config.duration_sec}s")
            await self.emit_progress(force=True)
            tasks = [asyncio.create_task(self.worker(i, session, semaphore)) for i in range(self.config.concurrency)]
            await asyncio.gather(*tasks)
        self.stop_at = 0.0
        print("[*] 压测结束，正在汇总结果...", flush=True)
        self.phase = "completed"
        await self.emit_progress(force=True)
        await self.emit_log("info", "压测结束，正在汇总结果")
        return self.summarize()

    async def run_matrix(
        self,
        *,
        existing_matrix_results: list[dict[str, Any]] | None = None,
        resume_policy: str = RESUME_POLICY_MISSING_OR_FAILED,
    ) -> list[Dict[str, Any]]:
        input_tokens_list = [int(x.strip()) for x in self.config.input_tokens_list.split(",")]
        concurrency_list = [int(x.strip()) for x in self.config.concurrency_list.split(",")]
        results_matrix = []
        reusable_results = {
            key: {**result, "matrix_resume_source": "existing"}
            for result in (existing_matrix_results or [])
            if (key := matrix_result_key(result)) and should_reuse_matrix_result(result, resume_policy)
        }
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
                point_key = matrix_point_key(input_tokens, concurrency)
                existing_result = reusable_results.get(point_key)
                if existing_result is not None:
                    existing_result["matrix_config"] = {
                        **(existing_result.get("matrix_config") or {}),
                        "input_tokens": input_tokens,
                        "concurrency": concurrency,
                        "test_index": current_test,
                        "total_tests": total_tests,
                    }
                    results_matrix.append(existing_result)
                    await self.emit_log("info", f"跳过已完成测试点 {input_tokens}/{concurrency}")
                    continue
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
                self.prompt, self.actual_input_tokens = self._prompt_for_tokens(input_tokens)
                print(f"[*] Prompt 构建完成，实际 token 数: {self.actual_input_tokens}", flush=True)
                self._refresh_executor()
                self.results = []
                self.metrics_accumulator.reset()
                self.request_counter = 0
                self._success_count = 0
                self._failure_count = 0
                self._success_token_count = 0
                self._success_cached_input_count = 0
                self._success_cache_inclusive_token_count = 0
                self._attempt_count = 0
                self._attempt_token_count = 0
                self._success_latency_window.clear()
                summary = await self.run()
                summary["matrix_config"] = {
                    "input_tokens": input_tokens,
                    "concurrency": concurrency,
                    "test_index": current_test,
                    "total_tests": total_tests,
                }
                if existing_matrix_results:
                    summary["matrix_resume_source"] = "rerun"
                results_matrix.append(summary)
                self.config.input_tokens = config_snapshot["input_tokens"]
                self.config.concurrency = config_snapshot["concurrency"]
                self.config.duration_sec = config_snapshot["duration_sec"]
                self._refresh_executor()
                if current_test < total_tests and not self.should_stop():
                    cooldown = 10
                    print(f"\n[*] 冷却 {cooldown} 秒后开始下一个测试点...\n")
                    await self.emit_log("info", f"冷却 {cooldown} 秒后开始下一个测试点")
                    if not await self._sleep_or_stop(cooldown):
                        break
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
