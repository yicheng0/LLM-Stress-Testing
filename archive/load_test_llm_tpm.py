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
from typing import Any, Dict, List, Optional, Tuple

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


class LoadTester:
    def __init__(self, args: argparse.Namespace):
        self.args = args
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

    async def next_request_id(self) -> int:
        async with self.counter_lock:
            self.request_counter += 1
            return self.request_counter

    def build_payload(self) -> Dict[str, Any]:
        # 默认按 chat.completions 格式发送；也支持 responses 接口。
        if self.args.endpoint.endswith("/responses"):
            return {
                "model": self.args.model,
                "input": self.prompt,
                "max_output_tokens": self.args.max_output_tokens,
                "temperature": self.args.temperature,
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
            "stream": False,
        }

    async def send_one(self, session: aiohttp.ClientSession, request_id: int) -> RequestResult:
        url = self.args.base_url.rstrip("/") + self.args.endpoint
        headers = {
            "Authorization": f"Bearer {self.args.api_key}",
            "Content-Type": "application/json",
        }
        payload = self.build_payload()

        attempt = 0
        started_at = time.time()
        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                async with session.post(url, headers=headers, json=payload, timeout=self.args.timeout_sec) as resp:
                    text = await resp.text()
                    t1 = time.perf_counter()
                    latency = t1 - t0

                    if 200 <= resp.status < 300:
                        output_tokens = 0
                        total_tokens = 0
                        ttft = None
                        try:
                            data = json.loads(text)
                            usage = data.get("usage", {}) if isinstance(data, dict) else {}
                            output_tokens = int(
                                usage.get("completion_tokens")
                                or usage.get("output_tokens")
                                or 0
                            )
                            total_tokens = int(usage.get("total_tokens") or 0)
                        except Exception:
                            data = None

                        if total_tokens <= 0:
                            total_tokens = self.actual_input_tokens + output_tokens

                        return RequestResult(
                            request_id=request_id,
                            ok=True,
                            status=resp.status,
                            started_at=started_at,
                            ended_at=time.time(),
                            latency_sec=latency,
                            ttft_sec=ttft,
                            input_tokens=self.actual_input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                            error_type=None,
                            error_message=None,
                            retry_count=attempt - 1,
                        )

                    # 可重试状态码
                    retryable = resp.status in {408, 409, 429, 500, 502, 503, 504}
                    if retryable and attempt <= self.args.max_retries:
                        await asyncio.sleep(self.backoff(attempt))
                        continue

                    return RequestResult(
                        request_id=request_id,
                        ok=False,
                        status=resp.status,
                        started_at=started_at,
                        ended_at=time.time(),
                        latency_sec=latency,
                        ttft_sec=None,
                        input_tokens=self.actual_input_tokens,
                        output_tokens=0,
                        total_tokens=self.actual_input_tokens,
                        error_type=f"HTTP_{resp.status}",
                        error_message=text[:1000],
                        retry_count=attempt - 1,
                    )
            except asyncio.TimeoutError as e:
                t1 = time.perf_counter()
                if attempt <= self.args.max_retries:
                    await asyncio.sleep(self.backoff(attempt))
                    continue
                return RequestResult(
                    request_id=request_id,
                    ok=False,
                    status=0,
                    started_at=started_at,
                    ended_at=time.time(),
                    latency_sec=t1 - t0,
                    ttft_sec=None,
                    input_tokens=self.actual_input_tokens,
                    output_tokens=0,
                    total_tokens=self.actual_input_tokens,
                    error_type="TIMEOUT",
                    error_message=str(e),
                    retry_count=attempt - 1,
                )
            except aiohttp.ClientError as e:
                t1 = time.perf_counter()
                if attempt <= self.args.max_retries:
                    await asyncio.sleep(self.backoff(attempt))
                    continue
                return RequestResult(
                    request_id=request_id,
                    ok=False,
                    status=0,
                    started_at=started_at,
                    ended_at=time.time(),
                    latency_sec=t1 - t0,
                    ttft_sec=None,
                    input_tokens=self.actual_input_tokens,
                    output_tokens=0,
                    total_tokens=self.actual_input_tokens,
                    error_type="CLIENT_ERROR",
                    error_message=str(e),
                    retry_count=attempt - 1,
                )
            except Exception as e:
                t1 = time.perf_counter()
                return RequestResult(
                    request_id=request_id,
                    ok=False,
                    status=0,
                    started_at=started_at,
                    ended_at=time.time(),
                    latency_sec=t1 - t0,
                    ttft_sec=None,
                    input_tokens=self.actual_input_tokens,
                    output_tokens=0,
                    total_tokens=self.actual_input_tokens,
                    error_type="UNKNOWN",
                    error_message=str(e),
                    retry_count=attempt - 1,
                )

    def backoff(self, attempt: int) -> float:
        base = min(self.args.retry_backoff_base * (2 ** (attempt - 1)), self.args.retry_backoff_max)
        jitter = random.uniform(0, base * 0.2)
        return base + jitter

    async def worker(self, worker_id: int, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore):
        while time.time() < self.stop_at:
            async with semaphore:
                req_id = await self.next_request_id()
                result = await self.send_one(session, req_id)
                self.results.append(result)
                ok_str = "OK" if result.ok else f"FAIL({result.error_type})"
                elapsed = int(time.time() - (self.stop_at - self.args.duration_sec))
                total = len(self.results)
                print(f"  [{elapsed:>4}s] req#{result.request_id} {ok_str} latency={result.latency_sec:.2f}s  已完成={total}", flush=True)
            if self.args.think_time_ms > 0:
                await asyncio.sleep(self.args.think_time_ms / 1000.0)

    async def run(self) -> Dict[str, Any]:
        connector = aiohttp.TCPConnector(limit=0, ssl=False)
        semaphore = asyncio.Semaphore(self.args.concurrency)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.args.connect_timeout_sec)

        self.stop_at = time.time() + self.args.duration_sec
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 预热
            if self.args.warmup_requests > 0:
                print(f"[*] 开始预热，发送 {self.args.warmup_requests} 个预热请求...", flush=True)
                warm_tasks = []
                for _ in range(self.args.warmup_requests):
                    req_id = await self.next_request_id()
                    warm_tasks.append(self.send_one(session, req_id))
                warm_res = await asyncio.gather(*warm_tasks, return_exceptions=False)
                self.results.extend(warm_res)
                print(f"[*] 预热完成", flush=True)

            # 正式压测
            print(f"[*] 开始正式压测，并发={self.args.concurrency}，时长={self.args.duration_sec}s ...", flush=True)
            tasks = [
                asyncio.create_task(self.worker(i, session, semaphore))
                for i in range(self.args.concurrency)
            ]
            await asyncio.gather(*tasks)
        print(f"[*] 压测结束，正在汇总结果...", flush=True)
        return self.summarize()

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

    def summarize(self) -> Dict[str, Any]:
        all_results = self.results
        success = [r for r in all_results if r.ok]
        failed = [r for r in all_results if not r.ok]
        latencies = [r.latency_sec for r in success]
        wall_time = self.args.duration_sec
        total_input_tokens = sum(r.input_tokens for r in success)
        total_output_tokens = sum(r.output_tokens for r in success)
        total_tokens = sum(r.total_tokens for r in success)
        error_counts = Counter(r.error_type or "UNKNOWN" for r in failed)
        status_counts = Counter(str(r.status) for r in all_results)

        summary = {
            "config": {
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
            },
            "results": {
                "total_requests": len(all_results),
                "successful_requests": len(success),
                "failed_requests": len(failed),
                "success_rate": round(len(success) / len(all_results), 4) if all_results else 0.0,
                "qps": round(len(success) / wall_time, 4) if wall_time > 0 else 0.0,
                "rpm": round(len(success) * 60 / wall_time, 4) if wall_time > 0 else 0.0,
                "input_tpm": round(total_input_tokens * 60 / wall_time, 2) if wall_time > 0 else 0.0,
                "output_tpm": round(total_output_tokens * 60 / wall_time, 2) if wall_time > 0 else 0.0,
                "total_tpm": round(total_tokens * 60 / wall_time, 2) if wall_time > 0 else 0.0,
                "latency_sec_avg": round(statistics.mean(latencies), 4) if latencies else None,
                "latency_sec_p50": round(self.percentile(latencies, 0.50), 4) if latencies else None,
                "latency_sec_p90": round(self.percentile(latencies, 0.90), 4) if latencies else None,
                "latency_sec_p95": round(self.percentile(latencies, 0.95), 4) if latencies else None,
                "latency_sec_p99": round(self.percentile(latencies, 0.99), 4) if latencies else None,
                "status_counts": dict(status_counts),
                "error_counts": dict(error_counts),
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
            },
        }
        return summary


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

    p95 = res.get("latency_sec_p95")
    if p95 is not None:
        if p95 > 60:
            conclusion.append("P95 延迟较高，长上下文推理或排队延迟可能是主要瓶颈。")
        elif p95 > 20:
            conclusion.append("P95 延迟偏高，建议结合服务端队列时长、prefill 时间和 decode 时间继续拆解。")
        else:
            conclusion.append("延迟表现较平稳，尾延迟可接受。")

    report = f"""# LLM API 压测报告

## 1. 测试目标
验证 LLM API 在 **100k 输入 tokens、并发 200** 条件下的稳定性、吞吐与延迟表现，重点观察：
- 是否能稳定承载长上下文 prefill 压力
- 在高并发下的成功率、尾延迟和错误分布
- 输入 TPM / 总 TPM 是否达到预期容量目标

## 2. 测试配置
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

## 3. 核心结果
- 总请求数: **{res['total_requests']}**
- 成功请求数: **{res['successful_requests']}**
- 失败请求数: **{res['failed_requests']}**
- 成功率: **{res['success_rate'] * 100:.2f}%**
- QPS: **{res['qps']}**
- RPM: **{res['rpm']}**
- 输入 TPM: **{res['input_tpm']}**
- 输出 TPM: **{res['output_tpm']}**
- 总 TPM: **{res['total_tpm']}**
- 平均延迟: **{res['latency_sec_avg']} s**
- P50 延迟: **{res['latency_sec_p50']} s**
- P90 延迟: **{res['latency_sec_p90']} s**
- P95 延迟: **{res['latency_sec_p95']} s**
- P99 延迟: **{res['latency_sec_p99']} s**

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

## 7. 结论与建议
1. **先确认模型上下文窗口**：并非所有模型都支持 100k 输入；若模型上下文上限低于该值，失败并不代表服务容量不足，而是请求规格不合法。
2. **重点拆分延迟结构**：建议服务端增加 queue time、prefill time、decode time、first token time 指标，避免只看端到端延迟。
3. **区分限流与容量瓶颈**：若 429 较多，优先调整配额和网关限速；若 5xx/超时较多，更可能是推理实例、KV cache 或上游网关瓶颈。
4. **逐级压测更有价值**：建议补充并发 50 / 100 / 150 / 200 的阶梯测试，找出拐点，而不是只做单点压测。
5. **长上下文建议单独评估**：100k prompt 主要施压 prefill 吞吐，不等价于短 prompt 业务场景；应与常规业务 prompt 分开建模。

## 8. 复现实验命令
```bash
python load_test_llm_api.py \\
  --base-url {cfg['base_url']} \\
  --api-key '$API_KEY' \\
  --model {cfg['model']} \\
  --endpoint {cfg['endpoint']} \\
  --concurrency {cfg['concurrency']} \\
  --duration-sec {cfg['duration_sec']} \\
  --input-tokens {cfg['input_tokens_actual']} \\
  --max-output-tokens {cfg['max_output_tokens']} \\
  --timeout-sec {cfg['timeout_sec']} \\
  --output-dir ./results
```
"""
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM API 压测脚本（OpenAI 兼容接口）")
    parser.add_argument("--base-url", default="https://api.wenwen-ai.com/v1", help="例如 https://host/v1")
    parser.add_argument("--api-key", default="sk", help="sk-G5JY02Ovu0HN6aEXc8wXfObOL7qVT30ulzNJewmVrwdDtovD")
    parser.add_argument("--model", default="glm-5.1", help="模型名")
    parser.add_argument("--endpoint", default="/chat/completions", help="/chat/completions 或 /responses")
    parser.add_argument("--concurrency", type=int, default=400)
    parser.add_argument("--duration-sec", type=int, default=300)
    parser.add_argument("--input-tokens", type=int, default=100000)
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
    return parser.parse_args()


def ensure_output_dir(path: str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def async_main() -> int:
    args = parse_args()
    out_dir = ensure_output_dir(args.output_dir)

    tester = LoadTester(args)
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

    print(json.dumps({
        "summary_file": str(summary_path),
        "details_file": str(detail_path),
        "report_file": str(report_path),
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
