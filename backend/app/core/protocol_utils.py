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
