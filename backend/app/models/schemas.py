from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal["queued", "running", "stopping", "completed", "failed", "cancelled", "interrupted"]


class TestCreate(BaseModel):
    name: str = Field(default="LLM API 性能测试", min_length=1, max_length=120)
    api_protocol: Literal["openai", "anthropic", "gemini"] = "openai"
    anthropic_version: str = Field(default="2023-06-01", min_length=1)
    base_url: str = Field(default="https://api.wenwen-ai.com", min_length=1)
    api_key: str = Field(..., min_length=1)
    model: str = Field(default="glm-5.1", min_length=1)
    endpoint: str = Field(default="/chat/completions")
    concurrency: int = Field(default=10, ge=1, le=1000)
    duration_sec: int = Field(default=60, ge=1, le=86400)
    input_tokens: int = Field(default=1000, ge=1)
    max_output_tokens: int = Field(default=128, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_sec: int = Field(default=600, ge=1)
    connect_timeout_sec: int = Field(default=30, ge=1)
    warmup_requests: int = Field(default=0, ge=0)
    max_retries: int = Field(default=2, ge=0)
    retry_backoff_base: float = Field(default=1.0, ge=0.0)
    retry_backoff_max: float = Field(default=8.0, ge=0.0)
    think_time_ms: int = Field(default=0, ge=0)
    enable_stream: bool = True
    matrix_mode: bool = False
    input_tokens_list: str = ""
    concurrency_list: str = ""
    matrix_duration_sec: int = Field(default=60, ge=1, le=86400)


class TestTaskOut(BaseModel):
    id: str
    name: str
    api_protocol: str = "openai"
    base_url: str
    endpoint: str
    model: str
    status: str
    concurrency: int
    duration_sec: int
    input_tokens: int
    max_output_tokens: int
    enable_stream: bool
    matrix_mode: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None = None
    progress: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    error_message: str | None = None


class TestListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[TestTaskOut]


class StartTestOut(BaseModel):
    test_id: str
    status: str
    created_at: datetime


class EventOut(BaseModel):
    id: int
    level: str
    message: str
    created_at: datetime


class ReportOut(BaseModel):
    test_id: str
    config: dict[str, Any]
    summary: dict[str, Any] | None
    charts: dict[str, Any] | None = None
    files: dict[str, str | None]
    events: list[EventOut]


class DetailsOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[dict[str, Any]]


class CleanupOut(BaseModel):
    deleted: int
    retention_hours: int
