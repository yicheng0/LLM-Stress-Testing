from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, quote, urlparse


class CurlConvertError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCurl:
    method: str
    url: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass(frozen=True)
class ConvertedDoc:
    protocol: str
    method: str
    endpoint: str
    model: str | None
    sanitized_curl: str
    openapi_yaml: str
    recognized_params: list[str]
    unknown_params: list[str]
    warnings: list[str]


BODY_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--json"}
HEADER_FLAGS = {"-H", "--header"}
METHOD_FLAGS = {"-X", "--request"}
FLAGS_WITH_VALUE = BODY_FLAGS | HEADER_FLAGS | METHOD_FLAGS | {"--url", "-u", "--user"}

KNOWN_BODY_PARAMS = {
    "openai": {
        "model",
        "messages",
        "input",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "temperature",
        "top_p",
        "stream",
        "stream_options",
        "stop",
        "tools",
        "tool_choice",
        "response_format",
        "presence_penalty",
        "frequency_penalty",
        "n",
        "user",
    },
    "anthropic": {
        "model",
        "messages",
        "system",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stream",
        "stop_sequences",
        "tools",
        "tool_choice",
        "metadata",
    },
    "gemini": {
        "contents",
        "systemInstruction",
        "generationConfig",
        "safetySettings",
        "tools",
        "toolConfig",
        "cachedContent",
    },
}


def convert_curl_to_openapi(curl: str, base_url: str, title: str) -> ConvertedDoc:
    parsed = parse_curl(curl)
    endpoint = normalize_endpoint(parsed.url)
    protocol = detect_protocol(parsed.headers, endpoint)
    sanitized_body = sanitize_json(parsed.body)
    warnings = build_warnings(parsed, protocol)
    model = extract_model(parsed.body, endpoint, protocol)
    recognized_params, unknown_params = classify_params(parsed.body, protocol)
    sanitized_curl = build_sanitized_curl(
        method=parsed.method,
        base_url=base_url,
        endpoint=endpoint,
        headers=parsed.headers,
        body=sanitized_body,
        protocol=protocol,
    )
    openapi = build_openapi_spec(
        title=title,
        base_url=base_url,
        endpoint=endpoint,
        method=parsed.method,
        body=sanitized_body,
        protocol=protocol,
        model=model,
        headers=parsed.headers,
    )
    validate_openapi(openapi)
    return ConvertedDoc(
        protocol=protocol,
        method=parsed.method,
        endpoint=endpoint,
        model=model,
        sanitized_curl=sanitized_curl,
        openapi_yaml=dump_yaml(openapi),
        recognized_params=recognized_params,
        unknown_params=unknown_params,
        warnings=warnings,
    )


def parse_curl(curl: str) -> ParsedCurl:
    normalized = normalize_curl_text(curl)
    try:
        tokens = shlex.split(normalized, posix=True)
    except ValueError as exc:
        raise CurlConvertError(f"curl 解析失败：{exc}") from exc

    if not tokens:
        raise CurlConvertError("curl 内容为空")
    if tokens[0].lower() == "curl":
        tokens = tokens[1:]

    method = "POST"
    url = ""
    headers: dict[str, str] = {}
    body_parts: list[str] = []

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in METHOD_FLAGS:
            index += 1
            method = require_value(tokens, index, token).upper()
        elif token in HEADER_FLAGS:
            index += 1
            name, value = parse_header(require_value(tokens, index, token))
            headers[name] = value
        elif token in BODY_FLAGS:
            index += 1
            body_parts.append(require_value(tokens, index, token))
        elif token == "--url":
            index += 1
            url = require_value(tokens, index, token)
        elif token.startswith("http://") or token.startswith("https://"):
            url = token
        elif token.startswith("-") and token in FLAGS_WITH_VALUE:
            index += 1
            require_value(tokens, index, token)
        index += 1

    if not url:
        raise CurlConvertError("未找到请求 URL")

    body_text = "".join(body_parts).strip()
    if not body_text:
        raise CurlConvertError("未找到 JSON 请求体")
    try:
        body = json.loads(body_text)
    except json.JSONDecodeError as exc:
        raise CurlConvertError(f"请求体不是合法 JSON：{exc.msg}") from exc
    if not isinstance(body, dict):
        raise CurlConvertError("请求体 JSON 顶层必须是对象")

    return ParsedCurl(method=method, url=url, headers=headers, body=body)


def normalize_curl_text(curl: str) -> str:
    text = curl.strip()
    text = text.replace("`\\\n", " ")
    text = re.sub(r"\\\s*\r?\n", " ", text)
    text = re.sub(r"\^\s*\r?\n", " ", text)
    text = re.sub(r"`\s*\r?\n", " ", text)
    return text


def require_value(tokens: list[str], index: int, flag: str) -> str:
    if index >= len(tokens):
        raise CurlConvertError(f"{flag} 缺少参数值")
    return tokens[index]


def parse_header(raw: str) -> tuple[str, str]:
    if ":" not in raw:
        raise CurlConvertError(f"请求头格式错误：{raw}")
    name, value = raw.split(":", 1)
    return name.strip(), value.strip()


def normalize_endpoint(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise CurlConvertError("URL 必须包含协议和域名")
    path = parsed.path or "/"
    query = sanitize_query(parsed.query)
    return f"{path}{query}"


def sanitize_query(query: str) -> str:
    if not query:
        return ""
    parts = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        safe_value = "${API_KEY}" if is_secret_name(key) else value
        parts.append(f"{quote(key)}={quote(safe_value, safe='${}')}")
    return f"?{'&'.join(parts)}" if parts else ""


def sanitize_json(value: Any, key_name: str = "") -> Any:
    if isinstance(value, dict):
        return {key: sanitize_json(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item, key_name) for item in value]
    if isinstance(value, str) and is_secret_name(key_name):
        return "${API_KEY}"
    return value


def is_secret_name(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized in {"apikey", "key", "token", "accesstoken", "authorization"}


def detect_protocol(headers: dict[str, str], endpoint: str) -> str:
    header_names = {name.lower() for name in headers}
    lowered_endpoint = endpoint.lower()
    if "x-goog-api-key" in header_names or "generatecontent" in lowered_endpoint:
        return "gemini"
    if "anthropic-version" in header_names or lowered_endpoint.endswith("/messages"):
        return "anthropic"
    return "openai"


def build_warnings(parsed: ParsedCurl, protocol: str) -> list[str]:
    warnings: list[str] = []
    if parsed.method != "POST":
        warnings.append(f"检测到 method 为 {parsed.method}，LLM 生成接口通常应为 POST。")
    if not parsed.body.get("model") and protocol != "gemini":
        warnings.append("请求体中未找到 model 字段，请确认导入后是否需要补充模型名。")
    if protocol == "gemini" and not extract_model(parsed.body, parsed.url, protocol):
        warnings.append("Gemini 请求未能从 URL 中识别模型名。")
    if not has_auth_header(parsed.headers, protocol):
        warnings.append("未检测到对应协议的鉴权请求头，导出内容将使用占位符鉴权。")
    return warnings


def has_auth_header(headers: dict[str, str], protocol: str) -> bool:
    names = {name.lower() for name in headers}
    if protocol == "gemini":
        return "x-goog-api-key" in names
    if protocol == "anthropic":
        return "x-api-key" in names
    return "authorization" in names


def extract_model(body: dict[str, Any], endpoint_or_url: str, protocol: str) -> str | None:
    model = body.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    if protocol == "gemini":
        match = re.search(r"/models/([^:/?]+)", endpoint_or_url)
        if match:
            return match.group(1)
    return None


def classify_params(body: dict[str, Any], protocol: str) -> tuple[list[str], list[str]]:
    known = KNOWN_BODY_PARAMS.get(protocol, KNOWN_BODY_PARAMS["openai"])
    keys = sorted(body.keys())
    recognized = [key for key in keys if key in known]
    unknown = [key for key in keys if key not in known]
    return recognized, unknown


def build_sanitized_curl(
    method: str,
    base_url: str,
    endpoint: str,
    headers: dict[str, str],
    body: dict[str, Any],
    protocol: str,
) -> str:
    output_headers = auth_headers(protocol, headers)
    lines = [
        f"curl -X {method} '{base_url.rstrip('/')}{endpoint}'",
    ]
    for name, value in output_headers.items():
        lines.append(f"  -H '{name}: {value}'")
    body_json = json.dumps(body, ensure_ascii=False, indent=2)
    lines.append(f"  -d '{body_json}'")
    return " \\\n".join(lines)


def auth_headers(protocol: str, source_headers: dict[str, str]) -> dict[str, str]:
    if protocol == "gemini":
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": "${API_KEY}",
        }
    if protocol == "anthropic":
        version = find_header(source_headers, "anthropic-version") or "2023-06-01"
        return {
            "Content-Type": "application/json",
            "x-api-key": "${API_KEY}",
            "anthropic-version": version,
        }
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer ${API_KEY}",
    }


def find_header(headers: dict[str, str], target: str) -> str | None:
    for name, value in headers.items():
        if name.lower() == target.lower():
            return value
    return None


def build_openapi_spec(
    title: str,
    base_url: str,
    endpoint: str,
    method: str,
    body: dict[str, Any],
    protocol: str,
    model: str | None,
    headers: dict[str, str],
) -> dict[str, Any]:
    operation_id = operation_id_for(protocol, endpoint)
    security_name = security_name_for(protocol)
    operation: dict[str, Any] = {
        "summary": summary_for(protocol, model),
        "operationId": operation_id,
        "security": [{security_name: []}],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object", "additionalProperties": True},
                    "example": body,
                }
            },
        },
        "responses": {
            "200": {
                "description": "Successful response",
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": True}
                    }
                },
            }
        },
    }
    if protocol == "anthropic":
        operation["parameters"] = [
            {
                "name": "anthropic-version",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
                "example": find_header(headers, "anthropic-version") or "2023-06-01",
            }
        ]

    openapi_path = endpoint.split("?", 1)[0]
    return {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": "1.0.0",
            "description": "由官方 curl 自动转换生成，API Key 已脱敏。",
        },
        "servers": [{"url": base_url.rstrip("/")}],
        "paths": {
            openapi_path: {
                method.lower(): operation,
            }
        },
        "components": {
            "securitySchemes": security_scheme(protocol),
        },
    }


def operation_id_for(protocol: str, endpoint: str) -> str:
    if protocol == "gemini":
        return "generateGeminiContent"
    if protocol == "anthropic":
        return "createAnthropicMessage"
    if endpoint.endswith("/responses"):
        return "createResponse"
    return "createChatCompletion"


def summary_for(protocol: str, model: str | None) -> str:
    labels = {
        "openai": "OpenAI-compatible 请求",
        "anthropic": "Anthropic Messages 请求",
        "gemini": "Gemini Content 请求",
    }
    suffix = f" - {model}" if model else ""
    return f"{labels.get(protocol, 'LLM API 请求')}{suffix}"


def security_name_for(protocol: str) -> str:
    if protocol == "gemini":
        return "GeminiApiKey"
    if protocol == "anthropic":
        return "AnthropicApiKey"
    return "BearerAuth"


def security_scheme(protocol: str) -> dict[str, Any]:
    if protocol == "gemini":
        return {
            "GeminiApiKey": {
                "type": "apiKey",
                "in": "header",
                "name": "x-goog-api-key",
            }
        }
    if protocol == "anthropic":
        return {
            "AnthropicApiKey": {
                "type": "apiKey",
                "in": "header",
                "name": "x-api-key",
            }
        }
    return {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
        }
    }


def validate_openapi(spec: dict[str, Any]) -> None:
    required = ["openapi", "info", "servers", "paths", "components"]
    missing = [key for key in required if key not in spec]
    if missing:
        raise CurlConvertError(f"OpenAPI 生成失败，缺少字段：{', '.join(missing)}")
    if not spec["paths"]:
        raise CurlConvertError("OpenAPI 生成失败，paths 为空")
    first_path = next(iter(spec["paths"].values()))
    first_operation = next(iter(first_path.values()))
    if "requestBody" not in first_operation:
        raise CurlConvertError("OpenAPI 生成失败，缺少 requestBody")
    schemes = spec.get("components", {}).get("securitySchemes")
    if not schemes:
        raise CurlConvertError("OpenAPI 生成失败，缺少 securitySchemes")


def dump_yaml(value: Any, indent: int = 0) -> str:
    lines = _yaml_lines(value, indent)
    return "\n".join(lines) + "\n"


def _yaml_lines(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            safe_key = str(key)
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{safe_key}:")
                lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{safe_key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        if not value:
            return [f"{prefix}[]"]
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_lines(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return json.dumps(text, ensure_ascii=False)
