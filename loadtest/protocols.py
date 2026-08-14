from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit, urlunparse

from .models import LEGACY_DEFAULT_ENDPOINTS, PROTOCOL_SPECS, ProtocolSpec, TokenUsage

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


def normalize_gemini_endpoint_mode(endpoint: str, enable_stream: bool) -> str:
    parts = urlsplit(endpoint)
    path = parts.path
    if enable_stream:
        path = path.replace(":generateContent", ":streamGenerateContent")
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "alt"]
        query.append(("alt", "sse"))
    else:
        path = path.replace(":streamGenerateContent", ":generateContent")
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "alt"]
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), parts.fragment))


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
    temperature: float | None,
    enable_stream: bool,
    cache_test_enabled: bool = False,
) -> dict[str, Any]:
    if protocol == "gemini":
        generation_config: dict[str, Any] = {
            "maxOutputTokens": max_output_tokens,
        }
        if temperature is not None:
            generation_config["temperature"] = temperature
        return {
            "systemInstruction": {"parts": [{"text": "You are a benchmarking target. Return a concise deterministic answer."}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }

    if protocol == "anthropic":
        content: str | list[dict[str, Any]] = prompt
        if cache_test_enabled:
            content = [{
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }]
        payload: dict[str, Any] = {
            "model": model,
            "system": "You are a benchmarking target. Return a concise deterministic answer.",
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_output_tokens,
            "stream": enable_stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    if normalize_endpoint(endpoint, "openai").endswith("/responses"):
        payload = {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "stream": enable_stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a benchmarking target. Return a concise deterministic answer."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_output_tokens,
        "stream": enable_stream,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def build_messages_payload(
    protocol: str,
    *,
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    max_output_tokens: int,
    temperature: float | None,
    enable_stream: bool,
    cache_prefix: str | None = None,
) -> dict[str, Any]:
    """Build a protocol payload for cache diagnostics without changing load-test payloads."""
    if protocol == "gemini":
        contents = []
        for message in messages:
            role = "model" if message.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": str(message.get("content") or "")}]})
        generation_config: dict[str, Any] = {"maxOutputTokens": max_output_tokens}
        if temperature is not None:
            generation_config["temperature"] = temperature
        return {"contents": contents, "generationConfig": generation_config}

    if protocol == "anthropic":
        anthropic_messages: list[dict[str, Any]] = []
        for message in messages:
            content = str(message.get("content") or "")
            rendered: str | list[dict[str, Any]] = content
            if cache_prefix and content.startswith(cache_prefix):
                rendered = [{"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}}]
                suffix = content[len(cache_prefix):]
                if suffix:
                    rendered.append({"type": "text", "text": suffix})
            anthropic_messages.append({"role": message.get("role", "user"), "content": rendered})
        payload: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_output_tokens,
            "stream": enable_stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    if normalize_endpoint(endpoint, "openai").endswith("/responses"):
        payload = {
            "model": model,
            "input": messages,
            "max_output_tokens": max_output_tokens,
            "stream": enable_stream,
        }
    else:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "stream": enable_stream,
        }
        if enable_stream:
            payload["stream_options"] = {"include_usage": True}
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


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
    if protocol == "gemini":
        endpoint = normalize_gemini_endpoint_mode(endpoint, enable_stream)
    return build_request_url(base_url, endpoint, protocol, model=model)


def _to_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _nested_int(data: dict[str, Any], *path: str) -> int:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    return _to_int(current)


def _has_path(data: dict[str, Any], *path: str) -> bool:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def extract_token_usage(usage: dict) -> TokenUsage:
    output_tokens = _to_int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("candidatesTokenCount")
    )
    input_tokens = _to_int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("promptTokenCount")
    )
    total_tokens = _to_int(usage.get("total_tokens") or usage.get("totalTokenCount"))

    cached_input_tokens = max(
        _nested_int(usage, "prompt_tokens_details", "cached_tokens"),
        _nested_int(usage, "input_tokens_details", "cached_tokens"),
        _to_int(usage.get("cachedContentTokenCount")),
        _to_int(usage.get("cache_read_input_tokens")),
        _to_int(usage.get("cached_input_tokens")),
        _to_int(usage.get("prompt_cache_hit_tokens")),
    )
    cache_creation_input_tokens = max(
        _to_int(usage.get("cache_creation_input_tokens")),
        _to_int(usage.get("cache_write_tokens")),
        _to_int(usage.get("cached_input_tokens_creation")),
    )
    cache_miss_tokens = max(
        _to_int(usage.get("prompt_cache_miss_tokens")),
        _to_int(usage.get("cache_miss_input_tokens")),
    )
    cache_usage_observed = any([
        _has_path(usage, "prompt_tokens_details", "cached_tokens"),
        _has_path(usage, "input_tokens_details", "cached_tokens"),
        "cachedContentTokenCount" in usage,
        "cache_read_input_tokens" in usage,
        "cache_creation_input_tokens" in usage,
        "cache_write_tokens" in usage,
        "cached_input_tokens" in usage,
        "cached_input_tokens_creation" in usage,
        "prompt_cache_hit_tokens" in usage,
        "prompt_cache_miss_tokens" in usage,
        "cache_miss_input_tokens" in usage,
    ])
    cache_tokens_additive = any(
        key in usage
        for key in ("cache_read_input_tokens", "cache_creation_input_tokens", "cache_write_tokens")
    )

    total_tokens_from_usage = total_tokens > 0
    if total_tokens <= 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens

    # Anthropic reports cache read/write tokens separately from input_tokens, so
    # cache-inclusive input needs to add them explicitly. OpenAI and Gemini
    # total token fields already include cached prompt content.
    if (
        usage.get("cache_read_input_tokens") is not None
        or usage.get("cache_creation_input_tokens") is not None
        or usage.get("cache_write_tokens") is not None
    ):
        cache_inclusive_total_tokens = input_tokens + output_tokens + cached_input_tokens + cache_creation_input_tokens
    elif cache_miss_tokens and not total_tokens_from_usage and input_tokens <= 0:
        cache_inclusive_total_tokens = cached_input_tokens + cache_miss_tokens + output_tokens
    else:
        cache_inclusive_total_tokens = total_tokens

    if cache_inclusive_total_tokens <= 0:
        cache_inclusive_total_tokens = total_tokens

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_inclusive_total_tokens=cache_inclusive_total_tokens,
        cache_usage_observed=cache_usage_observed,
        cache_tokens_additive=cache_tokens_additive,
    )


def extract_tokens(usage: dict) -> tuple[int, int]:
    parsed = extract_token_usage(usage)
    return parsed.output_tokens, parsed.total_tokens


def extract_response_text(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        return "".join(filter(None, (extract_response_text(item) for item in data)))
    if not isinstance(data, dict):
        return ""

    for key in ("output_text", "text", "completion", "delta"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value

    choices = data.get("choices")
    if isinstance(choices, list):
        text = "".join(extract_response_text(choice) for choice in choices)
        if text:
            return text

    candidates = data.get("candidates")
    if isinstance(candidates, list):
        text = "".join(extract_response_text(candidate) for candidate in candidates)
        if text:
            return text

    for key in ("message", "content", "parts", "output", "response", "content_block"):
        text = extract_response_text(data.get(key))
        if text:
            return text
    return ""


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
