from __future__ import annotations

from urllib.parse import urlsplit

BUILT_IN_BASE_URLS = {"https://api.wenwen-ai.com", "https://api.apipro.ai"}


def base_url_origin(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/").lower()
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/").lower()
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")


def is_built_in_base_url(value: str) -> bool:
    return base_url_origin(value) in BUILT_IN_BASE_URLS
