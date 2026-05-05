from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp

from backend.app.core.protocol_utils import (
    build_request_url,
    default_endpoint,
    normalize_endpoint,
    replace_model_placeholders,
)

AUTH_FAILURE_STATUSES = {401, 403}
LEGACY_DEFAULT_ENDPOINTS = {"/chat/completions", "/responses", "/messages"}


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    status: int | None = None
    message: str = ""
    body: str = ""


class PreflightError(ValueError):
    pass


def _protocol(payload: dict[str, Any]) -> str:
    return payload.get("api_protocol") or "openai"


def _endpoint(payload: dict[str, Any]) -> str:
    protocol = _protocol(payload)
    endpoint = payload.get("endpoint") or default_endpoint(protocol)
    if protocol == "gemini":
        if endpoint in LEGACY_DEFAULT_ENDPOINTS:
            endpoint = default_endpoint(protocol)
        endpoint = str(endpoint).replace(":streamGenerateContent", ":generateContent")
        endpoint = endpoint.split("?", 1)[0]
    model = payload.get("model") or "gemini-pro"
    return replace_model_placeholders(normalize_endpoint(endpoint, protocol), model)


def _url(payload: dict[str, Any]) -> str:
    return build_request_url(
        str(payload["base_url"]),
        _endpoint(payload),
        _protocol(payload),
        model=payload.get("model") or "gemini-pro",
    )


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    protocol = _protocol(payload)
    api_key = payload["api_key"]
    if protocol == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": payload.get("anthropic_version") or "2023-06-01",
            "Content-Type": "application/json",
        }
    if protocol == "gemini":
        return {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _body(payload: dict[str, Any]) -> dict[str, Any]:
    protocol = _protocol(payload)
    model = payload.get("model") or ""
    if protocol == "anthropic":
        return {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 16,
            "temperature": 0,
            "stream": False,
        }
    if protocol == "gemini":
        return {
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {
                "maxOutputTokens": 16,
                "temperature": 0,
            },
        }
    if str(payload.get("endpoint") or "").endswith("/responses"):
        return {
            "model": model,
            "input": "ping",
            "max_output_tokens": 16,
            "temperature": 0,
            "stream": False,
        }
    return {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
        "temperature": 0,
        "stream": False,
    }


def _extract_error_message(text: str) -> str:
    stripped = " ".join((text or "").strip().split())
    if not stripped:
        return ""
    return stripped[:300]


def _json_body(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_protocol_error(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or error.get("code") or "响应包含 error 字段")
    if error:
        return str(error)
    return None


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _usage_output_tokens(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    usage = data.get("usage") or data.get("usageMetadata") or {}
    if isinstance(usage, dict):
        for key in ("output_tokens", "completion_tokens", "candidatesTokenCount"):
            try:
                value = int(usage.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
    return 0


def _extract_model_text(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        for item in data:
            text = _extract_model_text(item)
            if text:
                return text
    if not isinstance(data, dict):
        return ""

    direct = _as_text(data.get("output_text")) or _as_text(data.get("text")) or _as_text(data.get("completion"))
    if direct:
        return direct

    content = data.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.extend([_as_text(item.get("text")), _as_text(item.get("content"))])
            else:
                parts.append(_as_text(item))
        text = "".join(part for part in parts if part)
        if text:
            return text

    choices = data.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            text = (
                _as_text(choice.get("text"))
                or _extract_model_text(choice.get("message") or {})
                or _extract_model_text(choice.get("delta") or {})
            )
            if text:
                return text

    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            text = _extract_model_text(item)
            if text:
                return text
    elif isinstance(output, dict):
        text = _extract_model_text(output)
        if text:
            return text

    candidates = data.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            text = _extract_model_text(candidate)
            if text:
                return text

    for key in ("data", "result", "response"):
        nested = data.get(key)
        if isinstance(nested, (dict, list, str)):
            text = _extract_model_text(nested)
            if text:
                return text

    return ""


def has_model_output(data: Any) -> bool:
    return bool(_extract_model_text(data)) or _usage_output_tokens(data) > 0


async def _post_probe(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
) -> tuple[int, str]:
    async with session.post(_url(payload), headers=_headers(payload), json=_body(payload)) as response:
        return response.status, await response.text()


async def validate_api_credentials(payload: dict[str, Any]) -> PreflightResult:
    timeout = aiohttp.ClientTimeout(
        total=min(max(int(payload.get("connect_timeout_sec") or 10), 1), 30),
        sock_connect=min(max(int(payload.get("connect_timeout_sec") or 10), 1), 15),
    )
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            status, text = await _post_probe(session, payload)
            data = _json_body(text)
            protocol_error = _extract_protocol_error(data)
            if status in AUTH_FAILURE_STATUSES:
                detail = _extract_error_message(text)
                message = "API Key 无效或无权限，请检查密钥、模型权限和接入域名"
                if detail:
                    message = f"{message}：{detail}"
                return PreflightResult(False, status, message, text[:1000])
            if not 200 <= status < 300:
                detail = _extract_error_message(text)
                message = f"启动前接口探测失败，HTTP {status}"
                if detail:
                    message = f"{message}：{detail}"
                return PreflightResult(False, status, message, text[:1000])
            if protocol_error:
                return PreflightResult(False, status, f"启动前接口探测返回错误：{protocol_error}", text[:1000])
            if not has_model_output(data):
                return PreflightResult(False, status, "启动前接口探测没有检测到真实模型输出", text[:1000])

            return PreflightResult(True, status, "启动前接口探测通过", text[:1000])
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise PreflightError("启动前接口探测超时，请检查接入域名、网络和模型服务状态") from exc
    except aiohttp.ClientError as exc:
        raise PreflightError(f"启动前接口探测失败，请检查接入域名和网络：{exc}") from exc
