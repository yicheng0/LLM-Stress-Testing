from __future__ import annotations

import json
import time
from typing import Any, Optional

import aiohttp

from .models import TokenUsage
from .protocols import extract_protocol_error, extract_token_usage, extract_tokens


class SseStreamParser:
    @staticmethod
    def parse_usage_text(stream_text: str) -> tuple[int, int]:
        usage = SseStreamParser.parse_token_usage_text(stream_text)
        return usage.output_tokens, usage.total_tokens

    @staticmethod
    def parse_token_usage_text(stream_text: str) -> TokenUsage:
        token_usage = TokenUsage()
        for data in SseStreamParser.iter_sse_json(stream_text):
            usage = SseStreamParser.extract_usage(data)
            if isinstance(usage, dict):
                token_usage = extract_token_usage(usage)
        return token_usage

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
        ttft, token_usage, protocol_error = await self.parse_stream_usage(content, request_started_perf)
        return ttft, token_usage.output_tokens, token_usage.total_tokens, protocol_error

    async def parse_stream_usage(
        self,
        content: aiohttp.StreamReader,
        request_started_perf: float,
    ) -> tuple[Optional[float], TokenUsage, Optional[str]]:
        buffer = bytearray()
        ttft = None
        token_usage = TokenUsage()
        protocol_error = None
        async for chunk in content.iter_any():
            if ttft is None and chunk:
                ttft = time.perf_counter() - request_started_perf
            if not chunk:
                continue
            buffer.extend(chunk)
            while True:
                line_end = buffer.find(b"\n")
                if line_end < 0:
                    break
                line = bytes(buffer[:line_end]).strip()
                del buffer[:line_end + 1]
                if not line.startswith(b"data: "):
                    continue
                data = line[6:]
                if data == b"[DONE]":
                    continue
                try:
                    data_obj = json.loads(data)
                except Exception:
                    continue
                protocol_error = extract_protocol_error(data_obj) or protocol_error
                usage = self.extract_usage(data_obj)
                if usage:
                    token_usage = extract_token_usage(usage)
        return ttft, token_usage, protocol_error
