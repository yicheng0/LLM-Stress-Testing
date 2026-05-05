from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit, urlunparse


PROTOCOL_VERSION_PREFIX = {
    "openai": "/v1",
    "anthropic": "/v1",
    "gemini": "/v1beta",
}


def protocol_version_prefix(protocol: str) -> str:
    return PROTOCOL_VERSION_PREFIX.get(protocol, "/v1")


def normalize_endpoint(endpoint: str, protocol: str) -> str:
    path = (endpoint or "").strip() or default_endpoint(protocol)
    path = normalize_gemini_stream_endpoint(path) if protocol == "gemini" else path
    prefix = protocol_version_prefix(protocol)
    if path == prefix:
        return "/"
    if path.startswith(prefix + "/"):
        path = path[len(prefix):]
    if not path.startswith("/"):
        path = "/" + path
    return path


def default_endpoint(protocol: str) -> str:
    if protocol == "gemini":
        return "/models/{model-name}:generateContent"
    if protocol == "anthropic":
        return "/messages"
    return "/chat/completions"


def normalize_gemini_stream_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    if not parts.query or "streamGenerateContent" not in parts.path:
        return endpoint
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not (key == "alt" and value == "sse")
    ]
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment,
    ))


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

    base_path = parsed.path.rstrip("/")
    if base_path.endswith(prefix):
        path = base_path + resolved_endpoint
    else:
        path = base_path + prefix + resolved_endpoint
    return urlunparse(parsed._replace(path=path))
