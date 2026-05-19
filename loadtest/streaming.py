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
        buffer = bytearray()
        ttft = None
        output_tokens = 0
        total_tokens = 0
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
                    output_tokens, total_tokens = extract_tokens(usage)
        return ttft, output_tokens, total_tokens, protocol_error
