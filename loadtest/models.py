from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


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
        default_base_url="https://api.wenwen-ai.com",
        stream_endpoint="/v1/chat/completions",
        non_stream_endpoint="/v1/chat/completions",
        default_model="gpt-5.5",
    ),
    "anthropic": ProtocolSpec(
        name="anthropic",
        label="Anthropic Messages",
        default_base_url="https://api.wenwen-ai.com",
        stream_endpoint="/messages",
        non_stream_endpoint="/messages",
        default_model="claude-sonnet-4-6-20260218",
    ),
    "gemini": ProtocolSpec(
        name="gemini",
        label="Gemini API",
        default_base_url="https://api.wenwen-ai.com",
        stream_endpoint="/v1beta/models/{model-name}:streamGenerateContent?alt=sse",
        non_stream_endpoint="/v1beta/models/{model-name}:generateContent",
        default_model="gemini-3.1-pro-preview",
    ),
}

LEGACY_DEFAULT_ENDPOINTS = {"/chat/completions", "/responses", "/messages"}

