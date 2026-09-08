from __future__ import annotations

import ipaddress
import socket
from urllib.parse import parse_qsl, urlsplit


REFERENCE_HOSTS = {
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
}


def _resolved_public(hostname: str) -> bool:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("域名无法解析") from exc
    if not addresses:
        raise ValueError("域名没有可用地址")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
            raise ValueError("端点解析到了非公网地址")
    return True


def validate_vendor_endpoint(value: str, *, reference: bool = False) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.lower() != "https":
        raise ValueError("供应商自测端点必须使用 HTTPS")
    if not parts.hostname or parts.username or parts.password:
        raise ValueError("端点必须是公网 HTTPS 地址，不能包含用户信息")
    if parts.fragment:
        raise ValueError("端点不能包含 fragment")
    if any(key.lower() in {"key", "api_key", "apikey", "token", "access_token", "secret"} for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise ValueError("API Key 不允许放在 URL 查询参数中")
    hostname = parts.hostname.rstrip(".").lower()
    if reference and hostname not in REFERENCE_HOSTS:
        raise ValueError("官方参考端点不在允许的域名白名单内")
    _resolved_public(hostname)
    return value.strip()
