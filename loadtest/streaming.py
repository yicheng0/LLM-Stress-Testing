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
                token_usage = SseStreamParser.merge_usage(token_usage, extract_token_usage(usage))
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
        if not usage and isinstance(data.get("response"), dict):
            usage = data["response"].get("usage") or data["response"].get("usageMetadata") or {}
        return usage if isinstance(usage, dict) else {}

    @staticmethod
    def extract_text_delta(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        event_type = str(data.get("type") or "")
        if event_type.endswith(".delta") and isinstance(data.get("delta"), str):
            return data["delta"]
        delta = data.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            return delta["text"]
        choices = data.get("choices")
        if isinstance(choices, list):
            parts = []
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                choice_delta = choice.get("delta") or {}
                content = choice_delta.get("content") if isinstance(choice_delta, dict) else None
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    parts.extend(str(item.get("text") or "") for item in content if isinstance(item, dict))
                if isinstance(choice.get("text"), str):
                    parts.append(choice["text"])
            return "".join(parts)
        candidates = data.get("candidates")
        if isinstance(candidates, list):
            parts = []
            for candidate in candidates:
                content = candidate.get("content") if isinstance(candidate, dict) else None
                for part in (content or {}).get("parts", []) if isinstance(content, dict) else []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        parts.append(part["text"])
            return "".join(parts)
        return ""

    @staticmethod
    def merge_usage(current: TokenUsage, parsed: TokenUsage) -> TokenUsage:
        input_tokens = max(current.input_tokens, parsed.input_tokens)
        output_tokens = max(current.output_tokens, parsed.output_tokens)
        cached_input_tokens = max(current.cached_input_tokens, parsed.cached_input_tokens)
        cache_creation_input_tokens = max(current.cache_creation_input_tokens, parsed.cache_creation_input_tokens)
        cache_tokens_additive = current.cache_tokens_additive or parsed.cache_tokens_additive
        total_tokens = max(current.total_tokens, parsed.total_tokens, input_tokens + output_tokens)
        if cache_tokens_additive:
            cache_inclusive_total_tokens = input_tokens + output_tokens + cached_input_tokens + cache_creation_input_tokens
        else:
            cache_inclusive_total_tokens = max(
                current.cache_inclusive_total_tokens,
                parsed.cache_inclusive_total_tokens,
                total_tokens,
            )
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_inclusive_total_tokens=cache_inclusive_total_tokens,
            cache_usage_observed=current.cache_usage_observed or parsed.cache_usage_observed,
            cache_tokens_additive=cache_tokens_additive,
        )

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
        ttft, token_usage, protocol_error, _response_text, _observed = await self.parse_stream_evidence(
            content,
            request_started_perf,
        )
        return ttft, token_usage, protocol_error

    async def parse_stream_evidence(
        self,
        content: aiohttp.StreamReader,
        request_started_perf: float,
    ) -> tuple[Optional[float], TokenUsage, Optional[str], str, bool]:
        buffer = bytearray()
        ttft = None
        token_usage = TokenUsage()
        protocol_error = None
        response_parts: list[str] = []
        observed_event = False
        async for chunk in content.iter_any():
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
                observed_event = True
                protocol_error = extract_protocol_error(data_obj) or protocol_error
                text_delta = self.extract_text_delta(data_obj)
                if text_delta:
                    if ttft is None:
                        ttft = time.perf_counter() - request_started_perf
                    response_parts.append(text_delta)
                usage = self.extract_usage(data_obj)
                if usage:
                    token_usage = self.merge_usage(token_usage, extract_token_usage(usage))
        return ttft, token_usage, protocol_error, "".join(response_parts), observed_event
