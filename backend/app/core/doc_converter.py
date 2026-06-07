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
    has_body: bool


@dataclass(frozen=True)
class ConvertedDoc:
    protocol: str
    method: str
    endpoint: str
    model: str | None
    headers: list[dict[str, str]]
    sanitized_curl: str
    openapi_yaml: str
    recognized_params: list[str]
    unknown_params: list[str]
    warnings: list[str]


BODY_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--json"}
HEADER_FLAGS = {"-H", "--header"}
METHOD_FLAGS = {"-X", "--request"}
FLAGS_WITH_VALUE = BODY_FLAGS | HEADER_FLAGS | METHOD_FLAGS | {"--url", "-u", "--user"}
SHORT_FLAGS_WITH_ATTACHED_VALUE = {
    "-d": "-d",
    "-H": "-H",
    "-X": "-X",
    "-u": "-u",
}
NO_VALUE_FLAGS = {
    "-L",
    "-N",
    "-S",
    "-i",
    "-k",
    "-s",
    "-v",
    "--compressed",
    "--fail",
    "--http1.1",
    "--http2",
    "--insecure",
    "--location",
    "--location-trusted",
    "--no-buffer",
    "--silent",
    "--verbose",
}

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
    output_headers = build_output_headers(protocol, parsed.headers)
    sanitized_curl = build_sanitized_curl(
        method=parsed.method,
        base_url=base_url,
        endpoint=endpoint,
        headers=output_headers,
        body=sanitized_body,
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
        output_headers=output_headers,
    )
    validate_openapi(openapi)
    return ConvertedDoc(
        protocol=protocol,
        method=parsed.method,
        endpoint=endpoint,
        model=model,
        headers=[{"name": name, "value": value} for name, value in output_headers.items()],
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
        flag, attached_value = split_flag_value(token)
        if flag in METHOD_FLAGS:
            value = attached_value
            if value is None:
                index += 1
                value = require_value(tokens, index, flag)
            method = value.upper()
        elif flag in HEADER_FLAGS:
            value = attached_value
            if value is None:
                index += 1
                value = require_value(tokens, index, flag)
            name, value = parse_header(value)
            headers[name] = value
        elif flag in BODY_FLAGS:
            value = attached_value
            if value is None:
                index += 1
                value = require_value(tokens, index, flag)
            body_parts.append(value)
        elif flag == "--url":
            value = attached_value
            if value is None:
                index += 1
                value = require_value(tokens, index, flag)
            url = value
        elif token.startswith("http://") or token.startswith("https://"):
            url = token
        elif flag in FLAGS_WITH_VALUE:
            index += 1
            require_value(tokens, index, flag)
        elif flag in NO_VALUE_FLAGS:
            pass
        index += 1

    if not url:
        raise CurlConvertError("未找到请求 URL")

    body_text = "".join(body_parts).strip()
    has_body = bool(body_text)
    body: dict[str, Any] = {}
    if has_body:
        try:
            body_value = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise CurlConvertError(f"请求体不是合法 JSON：{exc.msg}") from exc
        if not isinstance(body_value, dict):
            raise CurlConvertError("请求体 JSON 顶层必须是对象")
        body = body_value

    return ParsedCurl(method=method, url=url, headers=headers, body=body, has_body=has_body)


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


def split_flag_value(token: str) -> tuple[str, str | None]:
    if token.startswith("--") and "=" in token:
        flag, value = token.split("=", 1)
        return flag, value
    for prefix, flag in SHORT_FLAGS_WITH_ATTACHED_VALUE.items():
        if token.startswith(prefix) and token != prefix:
            return flag, token[len(prefix):]
    return token, None


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
    tokens = [item for item in re.split(r"[^a-z0-9]+", name.lower()) if item]
    if any(token in {"authorization", "cookie", "token", "key", "secret", "password", "credential"} for token in tokens):
        return True
    if "api" in tokens and "key" in tokens:
        return True
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized in {
        "apikey",
        "key",
        "token",
        "accesstoken",
        "accesskey",
        "authorization",
        "cookie",
        "setcookie",
        "xapikey",
        "xgoogapikey",
        "bearertoken",
    }


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
    if parsed.has_body and not parsed.body.get("model") and protocol != "gemini":
        warnings.append("请求体中未找到 model 字段，请确认导入后是否需要补充模型名。")
    if parsed.has_body and protocol == "gemini" and not extract_model(parsed.body, parsed.url, protocol):
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
    keys = sorted(body.keys())
    return keys, []


def build_sanitized_curl(
    method: str,
    base_url: str,
    endpoint: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> str:
    lines = [
        f"curl -X {method} '{base_url.rstrip('/')}{endpoint}'",
    ]
    for name, value in headers.items():
        lines.append(f"  -H '{name}: {value}'")
    if body:
        body_json = json.dumps(body, ensure_ascii=False, indent=2)
        lines.append(f"  -d '{body_json}'")
    return " \\\n".join(lines)


def build_output_headers(protocol: str, source_headers: dict[str, str]) -> dict[str, str]:
    output = auth_headers(protocol, source_headers)
    for name, value in source_headers.items():
        if is_protocol_auth_header(name, protocol):
            continue
        if name.lower() == "content-type":
            output["Content-Type"] = value or "application/json"
            continue
        if is_secret_name(name):
            continue
        output[name] = sanitize_header_value(name, value)
    if not has_header(output, "Content-Type"):
        ensure_header(output, "Content-Type", "application/json")
    return output


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


def ensure_header(headers: dict[str, str], name: str, value: str) -> None:
    if not find_header(headers, name):
        headers[name] = value


def has_header(headers: dict[str, str], target: str) -> bool:
    return find_header(headers, target) is not None


def is_protocol_auth_header(name: str, protocol: str) -> bool:
    lowered = name.lower()
    if protocol == "gemini":
        return lowered == "x-goog-api-key"
    if protocol == "anthropic":
        return lowered == "x-api-key"
    return lowered == "authorization"


def sanitize_header_value(name: str, value: str) -> str:
    return "${SECRET}" if is_secret_name(name) else value


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
    output_headers: dict[str, str],
) -> dict[str, Any]:
    operation_id = operation_id_for(protocol, endpoint)
    security_name = security_name_for(protocol)
    parameters = header_parameters(protocol, headers, output_headers)
    operation: dict[str, Any] = {
        "summary": summary_for(protocol, model),
        "operationId": operation_id,
        "security": [{security_name: []}],
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
    if body:
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": infer_json_schema(body),
                    "example": body,
                }
            },
        }
    if parameters:
        operation["parameters"] = parameters

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


def header_parameters(
    protocol: str,
    source_headers: dict[str, str],
    output_headers: dict[str, str],
) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for name, value in output_headers.items():
        lowered = name.lower()
        if lowered == "content-type" or is_protocol_auth_header(name, protocol):
            continue
        parameters.append(
            {
                "name": name,
                "in": "header",
                "required": lowered == "anthropic-version",
                "schema": {"type": "string"},
                "example": value,
            }
        )
    if protocol == "anthropic" and not any(item["name"].lower() == "anthropic-version" for item in parameters):
        parameters.append(
            {
                "name": "anthropic-version",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
                "example": find_header(source_headers, "anthropic-version") or "2023-06-01",
            }
        )
    return parameters


def infer_json_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        properties = {key: infer_json_schema(item) for key, item in value.items()}
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": True,
        }
        if properties:
            schema["required"] = list(properties.keys())
        return schema
    if isinstance(value, list):
        if not value:
            return {"type": "array", "items": {}}
        item_schemas = dedupe_schemas([infer_json_schema(item) for item in value])
        if len(item_schemas) == 1:
            return {"type": "array", "items": item_schemas[0]}
        return {"type": "array", "items": {"oneOf": item_schemas}}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    return {"type": "string"}


def dedupe_schemas(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for schema in schemas:
        key = json.dumps(schema, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        output.append(schema)
    return output


def operation_id_for(protocol: str, endpoint: str) -> str:
    if protocol == "gemini":
        return "generateGeminiContent"
    if protocol == "anthropic":
        return "createAnthropicMessage"
    if endpoint.endswith("/cancel"):
        return "cancelResponse"
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
