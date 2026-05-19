from __future__ import annotations

import asyncio
from email.utils import parsedate_to_datetime
import json
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import aiohttp

from .config import LoadTestConfig
from .models import RequestResult
from .protocols import build_headers, build_payload, build_url, extract_protocol_error, extract_tokens
from .streaming import SseStreamParser

BackoffFactory = Callable[[int], float]
RetrySleep = Callable[[float], Awaitable[bool]]


class RequestExecutor:
    def __init__(
        self,
        config: LoadTestConfig,
        *,
        prompt: str,
        actual_input_tokens: int,
        backoff: BackoffFactory,
        stream_parser: SseStreamParser | None = None,
        retry_sleep: RetrySleep | None = None,
    ):
        self.config = config
        self.prompt = prompt
        self.actual_input_tokens = actual_input_tokens
        self.backoff = backoff
        self.retry_sleep = retry_sleep or self._default_retry_sleep
        self.stream_parser = stream_parser or SseStreamParser()
        self._url = self.build_url()
        self._headers = self.build_headers()
        self._payload = self.build_payload()

    @staticmethod
    async def _default_retry_sleep(seconds: float) -> bool:
        if seconds > 0:
            await asyncio.sleep(seconds)
        return True

    def _retry_delay(self, attempt: int, retry_after: str | None = None) -> float:
        delay = self.backoff(attempt)
        if not retry_after:
            return delay
        parsed_delay = self._parse_retry_after(retry_after)
        if parsed_delay is None:
            return delay
        return min(max(0.0, parsed_delay), self.config.retry_backoff_max)

    @staticmethod
    def _parse_retry_after(value: str) -> float | None:
        value = value.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed - datetime.now(timezone.utc)).total_seconds()

    async def _sleep_before_retry(self, attempt: int, retry_after: str | None = None) -> None:
        completed = await self.retry_sleep(self._retry_delay(attempt, retry_after))
        if not completed:
            raise asyncio.CancelledError

    def build_payload(self) -> dict:
        return build_payload(
            self.config.api_protocol,
            endpoint=self.config.endpoint,
            model=self.config.model,
            prompt=self.prompt,
            max_output_tokens=self.config.max_output_tokens,
            temperature=self.config.temperature,
            enable_stream=self.config.enable_stream,
        )

    def build_headers(self) -> dict[str, str]:
        return build_headers(
            self.config.api_protocol,
            api_key=self.config.api_key or "",
            anthropic_version=self.config.anthropic_version,
        )

    def build_url(self) -> str:
        return build_url(
            self.config.base_url,
            self.config.endpoint,
            self.config.api_protocol,
            model=self.config.model,
            enable_stream=self.config.enable_stream,
        )

    def create_result(
        self,
        request_id: int,
        started_at: float,
        request_started_perf: float,
        ok: bool,
        status: int = 0,
        ttft: Optional[float] = None,
        output_tokens: int = 0,
        total_tokens: Optional[int] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        attempt: int = 1,
    ) -> RequestResult:
        if total_tokens is None:
            total_tokens = self.actual_input_tokens + output_tokens
        return RequestResult(
            request_id=request_id,
            ok=ok,
            status=status,
            started_at=started_at,
            ended_at=time.time(),
            latency_sec=time.perf_counter() - request_started_perf,
            ttft_sec=ttft,
            input_tokens=self.actual_input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            error_type=error_type,
            error_message=error_message,
            retry_count=attempt - 1,
        )

    async def send_one(self, session: aiohttp.ClientSession, request_id: int) -> RequestResult:
        attempt = 0
        started_at = time.time()
        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                async with session.post(self._url, headers=self._headers, json=self._payload, timeout=self.config.timeout_sec) as resp:
                    if 200 <= resp.status < 300:
                        if self.config.enable_stream:
                            try:
                                ttft, output_tokens, total_tokens, protocol_error = await self.stream_parser.parse_stream(resp.content, t0)
                                if protocol_error:
                                    return self.create_result(
                                        request_id,
                                        started_at,
                                        t0,
                                        False,
                                        resp.status,
                                        ttft=ttft,
                                        output_tokens=0,
                                        total_tokens=self.actual_input_tokens,
                                        error_type="PROTOCOL_ERROR",
                                        error_message=protocol_error,
                                        attempt=attempt,
                                    )
                                return self.create_result(
                                    request_id,
                                    started_at,
                                    t0,
                                    True,
                                    resp.status,
                                    ttft=ttft,
                                    output_tokens=output_tokens,
                                    total_tokens=total_tokens if total_tokens > 0 else None,
                                    attempt=attempt,
                                )
                            except Exception as exc:
                                return self.create_result(
                                    request_id,
                                    started_at,
                                    t0,
                                    False,
                                    resp.status,
                                    output_tokens=0,
                                    total_tokens=self.actual_input_tokens,
                                    error_type="STREAM_PARSE_ERROR",
                                    error_message=f"流式响应解析失败: {exc}",
                                    attempt=attempt,
                                )
                        text = await resp.text()
                        try:
                            data = json.loads(text)
                            usage = {}
                            if isinstance(data, dict):
                                protocol_error = extract_protocol_error(data)
                                if protocol_error:
                                    return self.create_result(
                                        request_id,
                                        started_at,
                                        t0,
                                        False,
                                        resp.status,
                                        output_tokens=0,
                                        total_tokens=self.actual_input_tokens,
                                        error_type="PROTOCOL_ERROR",
                                        error_message=protocol_error,
                                        attempt=attempt,
                                    )
                                usage = data.get("usage") or data.get("usageMetadata") or {}
                            output_tokens, total_tokens = extract_tokens(usage)
                        except Exception:
                            output_tokens, total_tokens = 0, 0
                        return self.create_result(
                            request_id,
                            started_at,
                            t0,
                            True,
                            resp.status,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens if total_tokens > 0 else None,
                            attempt=attempt,
                        )

                    text = await resp.text()
                    retryable = resp.status in {408, 409, 429, 500, 502, 503, 504}
                    if retryable and attempt <= self.config.max_retries:
                        await self._sleep_before_retry(attempt, resp.headers.get("Retry-After"))
                        continue
                    return self.create_result(
                        request_id,
                        started_at,
                        t0,
                        False,
                        resp.status,
                        output_tokens=0,
                        total_tokens=self.actual_input_tokens,
                        error_type=f"HTTP_{resp.status}",
                        error_message=text[:1000],
                        attempt=attempt,
                    )
            except asyncio.TimeoutError as exc:
                if attempt <= self.config.max_retries:
                    await self._sleep_before_retry(attempt)
                    continue
                return self.create_result(request_id, started_at, t0, False, 0, output_tokens=0, total_tokens=self.actual_input_tokens, error_type="TIMEOUT", error_message=str(exc), attempt=attempt)
            except aiohttp.ClientError as exc:
                if attempt <= self.config.max_retries:
                    await self._sleep_before_retry(attempt)
                    continue
                return self.create_result(request_id, started_at, t0, False, 0, output_tokens=0, total_tokens=self.actual_input_tokens, error_type="CLIENT_ERROR", error_message=str(exc), attempt=attempt)
            except Exception as exc:
                return self.create_result(request_id, started_at, t0, False, 0, output_tokens=0, total_tokens=self.actual_input_tokens, error_type="UNKNOWN", error_message=str(exc), attempt=attempt)
