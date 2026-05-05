from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp


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
    endpoint = payload.get("endpoint") or "/chat/completions"
    if protocol == "gemini":
        if endpoint in LEGACY_DEFAULT_ENDPOINTS:
            endpoint = "/models/{model}:generateContent"
        endpoint = endpoint.replace("{model}", payload.get("model") or "gemini-pro")
    return endpoint


def _url(payload: dict[str, Any]) -> str:
    return str(payload["base_url"]).rstrip("/") + _endpoint(payload)


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
            "max_tokens": 1,
            "temperature": 0,
            "stream": False,
        }
    if protocol == "gemini":
        return {
            "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
            "generationConfig": {
                "maxOutputTokens": 1,
                "temperature": 0,
            },
        }
    return {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }


def _extract_error_message(text: str) -> str:
    stripped = " ".join((text or "").strip().split())
    if not stripped:
        return ""
    return stripped[:300]


async def validate_api_credentials(payload: dict[str, Any]) -> PreflightResult:
    timeout = aiohttp.ClientTimeout(
        total=min(max(int(payload.get("connect_timeout_sec") or 10), 1), 30),
        sock_connect=min(max(int(payload.get("connect_timeout_sec") or 10), 1), 15),
    )
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(_url(payload), headers=_headers(payload), json=_body(payload)) as response:
                text = await response.text()
                if response.status in AUTH_FAILURE_STATUSES:
                    detail = _extract_error_message(text)
                    message = "API Key 无效或无权限，请检查密钥、模型权限和接入域名"
                    if detail:
                        message = f"{message}：{detail}"
                    return PreflightResult(False, response.status, message, text[:1000])
                if 200 <= response.status < 300:
                    return PreflightResult(True, response.status, "鉴权探测通过", text[:1000])
                detail = _extract_error_message(text)
                message = f"启动前接口探测失败，HTTP {response.status}"
                if detail:
                    message = f"{message}：{detail}"
                return PreflightResult(False, response.status, message, text[:1000])
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise PreflightError("启动前接口探测超时，请检查接入域名、网络和模型服务状态") from exc
    except aiohttp.ClientError as exc:
        raise PreflightError(f"启动前接口探测失败，请检查接入域名和网络：{exc}") from exc
