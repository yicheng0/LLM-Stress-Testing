from __future__ import annotations

import json
import time
from typing import Any, Optional

import aiohttp

from .protocols import extract_protocol_error, extract_tokens


class SseStreamParser:
    @staticmethod
    def parse_usage_text(stream_text: str) -> tuple[int, int]:
        output_tokens = 0
        total_tokens = 0
        for data in SseStreamParser.iter_sse_json(stream_text):
            usage = SseStreamParser.extract_usage(data)
            if isinstance(usage, dict):
                output_tokens, total_tokens = extract_tokens(usage)
        return output_tokens, total_tokens

    @staticmethod
    def iter_sse_json(text: str):
        for line in text.split("\n"):
            line = line.strip()
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                yield json.loads(data_str)
            except Exception:
                continue

    @staticmethod
    def extract_usage(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        usage = data.get("usage") or data.get("usageMetadata") or {}
        if not usage and isinstance(data.get("message"), dict):
            usage = data["message"].get("usage") or {}
        return usage if isinstance(usage, dict) else {}

    async def parse_stream(
        self,
        content: aiohttp.StreamReader,
        request_started_perf: float,
    ) -> tuple[Optional[float], int, int, Optional[str]]:
        buffer = ""
        ttft = None
        output_tokens = 0
        total_tokens = 0
        protocol_error = None
        async for chunk in content.iter_any():
            if ttft is None and chunk:
                ttft = time.perf_counter() - request_started_perf
            buffer += chunk.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue
                protocol_error = extract_protocol_error(data) or protocol_error
                usage = self.extract_usage(data)
                if usage:
                    output_tokens, total_tokens = extract_tokens(usage)
        return ttft, output_tokens, total_tokens, protocol_error
