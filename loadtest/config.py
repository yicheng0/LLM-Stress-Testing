from __future__ import annotations

import argparse
from dataclasses import dataclass, fields
from typing import Any, Mapping


@dataclass
class LoadTestConfig:
    api_protocol: str = "openai"
    anthropic_version: str = "2023-06-01"
    base_url: str = "https://api.wenwen-ai.com"
    api_key: str | None = None
    model: str = "gpt-5.5"
    endpoint: str = "/v1/chat/completions"
    concurrency: int = 500
    duration_sec: int = 300
    input_tokens: int = 60000
    max_output_tokens: int = 128
    temperature: float = 0.0
    timeout_sec: int = 600
    connect_timeout_sec: int = 30
    warmup_requests: int = 5
    max_retries: int = 2
    retry_backoff_base: float = 1.0
    retry_backoff_max: float = 8.0
    think_time_ms: int = 0
    output_dir: str = "./results"
    enable_stream: bool = True
    matrix_mode: bool = False
    input_tokens_list: str = "60000,80000,100000"
    concurrency_list: str = "300,500,700"
    matrix_duration_sec: int = 300

    @classmethod
    def from_namespace(cls, namespace: argparse.Namespace) -> "LoadTestConfig":
        return cls.from_mapping(vars(namespace))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "LoadTestConfig":
        names = {field.name for field in fields(cls)}
        data = {name: values[name] for name in names if name in values}
        config = cls(**data)
        config.coerce_types()
        return config

    @classmethod
    def coerce(cls, value: "LoadTestConfig | argparse.Namespace | Mapping[str, Any]") -> "LoadTestConfig":
        if isinstance(value, cls):
            value.coerce_types()
            return value
        if isinstance(value, argparse.Namespace):
            return cls.from_namespace(value)
        return cls.from_mapping(value)

    def coerce_types(self) -> None:
        self.api_protocol = str(self.api_protocol or "openai")
        self.anthropic_version = str(self.anthropic_version or "2023-06-01")
        self.base_url = str(self.base_url)
        self.api_key = None if self.api_key is None else str(self.api_key)
        self.model = str(self.model)
        self.endpoint = str(self.endpoint or "")
        self.concurrency = int(self.concurrency)
        self.duration_sec = int(self.duration_sec)
        self.input_tokens = int(self.input_tokens)
        self.max_output_tokens = int(self.max_output_tokens)
        self.temperature = float(self.temperature)
        self.timeout_sec = int(self.timeout_sec)
        self.connect_timeout_sec = int(self.connect_timeout_sec)
        self.warmup_requests = int(self.warmup_requests)
        self.max_retries = int(self.max_retries)
        self.retry_backoff_base = float(self.retry_backoff_base)
        self.retry_backoff_max = float(self.retry_backoff_max)
        self.think_time_ms = int(self.think_time_ms)
        self.output_dir = str(self.output_dir)
        self.enable_stream = bool(self.enable_stream)
        self.matrix_mode = bool(self.matrix_mode)
        self.input_tokens_list = str(self.input_tokens_list or "")
        self.concurrency_list = str(self.concurrency_list or "")
        self.matrix_duration_sec = int(self.matrix_duration_sec)

    def to_namespace(self) -> argparse.Namespace:
        return argparse.Namespace(**self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def safe_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("api_key", None)
        return data
