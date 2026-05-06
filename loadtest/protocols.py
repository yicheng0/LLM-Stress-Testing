from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit, urlunparse

from .models import LEGACY_DEFAULT_ENDPOINTS, PROTOCOL_SPECS, ProtocolSpec

PROTOCOL_VERSION_PREFIX = {
    "openai": "/v1",
    "anthropic": "/v1",
    "gemini": "/v1beta",
}


def protocol_spec(protocol: str) -> ProtocolSpec:
    return PROTOCOL_SPECS.get(protocol, PROTOCOL_SPECS["openai"])


def protocol_version_prefix(protocol: str) -> str:
    return PROTOCOL_VERSION_PREFIX.get(protocol, "/v1")


def default_endpoint(protocol: str) -> str:
    if protocol == "gemini":
        return "/models/{model-name}:generateContent"
    if protocol == "anthropic":
        return "/messages"
    return "/chat/completions"


def normalize_gemini_stream_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    if "streamGenerateContent" not in parts.path:
        return endpoint
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "alt"
    ]
    query.append(("alt", "sse"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_endpoint(endpoint: str, protocol: str) -> str:
    endpoint = (endpoint or "").strip() or default_endpoint(protocol)
    endpoint = normalize_gemini_stream_endpoint(endpoint) if protocol == "gemini" else endpoint
    parts = urlsplit(endpoint)
    path = parts.path
    prefix = protocol_version_prefix(protocol)
    if path == prefix:
        path = "/"
    elif path.startswith(prefix + "/"):
        path = path[len(prefix):]
    elif not path.startswith("/"):
        path = "/" + path
    return urlunsplit(("", "", path, parts.query, parts.fragment))


def replace_model_placeholders(endpoint: str, model: str) -> str:
    return (
        endpoint
        .replace("{model-name}", model)
        .replace("{model}", model)
        .replace("%7Bmodel-name%7D", model)
        .replace("%7bmodel-name%7d", model)
        .replace("%7Bmodel%7D", model)
        .replace("%7bmodel%7d", model)
    )


def build_request_url(base_url: str, endpoint: str, protocol: str, *, model: str | None = None) -> str:
    parsed = urlparse(str(base_url).rstrip("/"))
    prefix = protocol_version_prefix(protocol)
    resolved_endpoint = normalize_endpoint(endpoint, protocol)
    if model:
        resolved_endpoint = replace_model_placeholders(resolved_endpoint, model)
    endpoint_parts = urlsplit(resolved_endpoint)

    base_path = parsed.path.rstrip("/")
    for known_prefix in sorted(set(PROTOCOL_VERSION_PREFIX.values()), key=len, reverse=True):
        if base_path == known_prefix:
            base_path = ""
            break
        if base_path.endswith(known_prefix):
            base_path = base_path[:-len(known_prefix)].rstrip("/")
            break

    path = base_path + prefix + endpoint_parts.path
    query = endpoint_parts.query or parsed.query
    return urlunparse(parsed._replace(path=path, query=query, fragment=endpoint_parts.fragment))


def build_payload(
    protocol: str,
    *,
    endpoint: str,
    model: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
    enable_stream: bool,
) -> dict[str, Any]:
    if protocol == "gemini":
        return {
            "systemInstruction": {"parts": [{"text": "You are a benchmarking target. Return a concise deterministic answer."}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "temperature": temperature,
            },
        }

    if protocol == "anthropic":
        return {
            "model": model,
            "system": "You are a benchmarking target. Return a concise deterministic answer.",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "stream": enable_stream,
        }

    if normalize_endpoint(endpoint, "openai").endswith("/responses"):
        return {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "temperature": temperature,
            "stream": enable_stream,
        }

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a benchmarking target. Return a concise deterministic answer."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_output_tokens,
        "temperature": temperature,
        "stream": enable_stream,
    }


def build_headers(protocol: str, *, api_key: str, anthropic_version: str = "2023-06-01") -> dict[str, str]:
    if protocol == "gemini":
        return {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    if protocol == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": anthropic_version,
            "Content-Type": "application/json",
        }
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def build_url(base_url: str, endpoint: str, protocol: str, *, model: str | None = None, enable_stream: bool = True) -> str:
    spec = protocol_spec(protocol)
    if protocol == "gemini" and (not endpoint or endpoint in LEGACY_DEFAULT_ENDPOINTS):
        endpoint = spec.default_endpoint(enable_stream)
    return build_request_url(base_url, endpoint, protocol, model=model)


def extract_tokens(usage: dict) -> tuple[int, int]:
    output_tokens = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("candidatesTokenCount")
        or 0
    )
    input_tokens = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("promptTokenCount")
        or 0
    )
    total_tokens = int(usage.get("total_tokens") or usage.get("totalTokenCount") or 0)
    if total_tokens <= 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    return output_tokens, total_tokens


def extract_protocol_error(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or error.get("code")
        if message:
            return str(message)
        return "响应包含 error 字段"
    if error:
        return str(error)
    return None
