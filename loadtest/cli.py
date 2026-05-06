from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .config import LoadTestConfig
from .result_writer import ReportArtifactWriter
from .runner import LoadTestRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM API 压测脚本（OpenAI-compatible / Anthropic Messages / Gemini）")
    parser.add_argument("--api-protocol", choices=["openai", "anthropic", "gemini"], default="openai", help="接口协议类型")
    parser.add_argument("--anthropic-version", default="2023-06-01", help="Anthropic API 版本请求头")
    parser.add_argument("--base-url", default="https://api.wenwen-ai.com", help="例如 https://api.wenwen-ai.com")
    parser.add_argument("--api-key", default=os.getenv("API_KEY") or os.getenv("LLM_API_KEY"), help="API Key，默认读取 API_KEY 或 LLM_API_KEY 环境变量")
    parser.add_argument("--model", default="gpt-5.5", help="模型名")
    parser.add_argument("--endpoint", default="/v1/chat/completions", help="/v1/chat/completions 或 /v1/responses")
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
    stream_group = parser.add_mutually_exclusive_group()
    stream_group.add_argument("--enable-stream", dest="enable_stream", action="store_true", default=True, help="启用流式响应以测量 TTFT")
    stream_group.add_argument("--disable-stream", dest="enable_stream", action="store_false", help="关闭流式响应")
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
    if not args.api_key:
        print("错误：请通过 --api-key、API_KEY 或 LLM_API_KEY 提供 API Key", file=sys.stderr)
        return 2
    config = LoadTestConfig.from_namespace(args)
    out_dir = ensure_output_dir(config.output_dir)
    writer = ReportArtifactWriter(out_dir)
    tester = LoadTestRunner(config)
    if config.matrix_mode:
        if not config.input_tokens_list or not config.concurrency_list:
            print("错误：矩阵模式需要指定 --input-tokens-list 和 --concurrency-list", file=sys.stderr)
            return 1
        results_matrix = await tester.run_matrix()
        files = writer.write_matrix(results_matrix)
        print(json.dumps({
            "matrix_summary_file": files["summary_path"],
            "matrix_report_file": files["report_md_path"],
            "matrix_csv_file": files["matrix_csv_path"],
            "test_points": len(results_matrix),
        }, ensure_ascii=False, indent=2))
        return 0

    summary = await tester.run()
    files = writer.write_single(summary, tester.results)
    print(json.dumps({
        "summary_file": files["summary_path"],
        "details_file": files["details_jsonl_path"],
        "report_file": files["report_md_path"],
        "html_report_file": files["report_html_path"],
        "summary": summary,
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
