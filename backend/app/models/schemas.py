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
    model: str = Field(default="gpt-5.5", min_length=1)
    endpoint: str = Field(default="/v1/chat/completions")
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
    expected_metrics: dict[str, Any] | None = None


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
    expected_metrics: dict[str, Any] | None = None
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
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    retention_hours: int


class DetailsOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[dict[str, Any]]


class CleanupOut(BaseModel):
    deleted: int
    retention_hours: int


class BulkDeleteIn(BaseModel):
    ids: list[str] = Field(default_factory=list)


class BulkDeleteOut(BaseModel):
    requested: int
    deleted: int
    not_found: list[str]


class VersionInfoOut(BaseModel):
    available: bool = True
    update_enabled: bool = False
    current_version: str
    current_ref: str | None = None
    latest_ref: str | None = None
    branch: str | None = None
    remote_url: str | None = None
    ahead_count: int | None = None
    behind_count: int | None = None
    dirty: bool | None = None
    dirty_paths: list[str] | None = None
    update_available: bool = False
    message: str | None = None
    checked_at: datetime | None = None


class VersionUpdateRequest(BaseModel):
    force: bool = False


class VersionUpdateOut(BaseModel):
    success: bool
    message: str
    current_ref: str | None = None
    latest_ref: str | None = None
    restart_required: bool = True
    stdout: str | None = None
    stderr: str | None = None


class CurlConvertRequest(BaseModel):
    curl: str = Field(..., min_length=1)
    base_url: str = Field(default="https://api.wenwen-ai.com", min_length=1)
    title: str = Field(default="LLM API 接口文档", min_length=1, max_length=120)


class CurlConvertOut(BaseModel):
    protocol: Literal["openai", "anthropic", "gemini"]
    method: str
    endpoint: str
    model: str | None = None
    sanitized_curl: str
    openapi_yaml: str
    recognized_params: list[str]
    unknown_params: list[str]
    warnings: list[str]
