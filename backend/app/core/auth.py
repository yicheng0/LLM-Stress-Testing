from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from fastapi import Depends, Header, HTTPException, status

from backend.app.config import settings

Role = Literal["root", "guest"]
ROOT_USERNAME = "root"
ROOT_PASSWORD = "banma666"


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: Role


def hash_password(password: str, *, salt: str | None = None, iterations: int = 260_000) -> str:
    salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${base64.urlsafe_b64encode(digest).decode('ascii')}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hash_password(password, salt=salt, iterations=int(raw_iterations)).split("$", 3)[3]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def load_users() -> dict[str, dict[str, str]]:
    path = settings.auth_config_path
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    users: dict[str, dict[str, str]] = {}
    for item in data.get("users", []):
        username = str(item.get("username") or "").strip()
        role = str(item.get("role") or "").strip()
        password_hash = str(item.get("password_hash") or "").strip()
        if username and role in {"root", "guest"} and password_hash:
            users[username] = {"role": role, "password_hash": password_hash}
    return users


def authenticate_user(username: str, password: str) -> AuthUser | None:
    if username == ROOT_USERNAME:
        if hmac.compare_digest(password, ROOT_PASSWORD):
            return AuthUser(username=ROOT_USERNAME, role="root")
        return None
    item = load_users().get(username)
    if not item or not verify_password(password, item["password_hash"]):
        return None
    return AuthUser(username=username, role=item["role"])  # type: ignore[arg-type]


def create_guest_user() -> AuthUser:
    return AuthUser(username=f"guest_{secrets.token_urlsafe(8)}", role="guest")


def _b64_json(data: dict[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64_json(value: str) -> dict[str, object]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))


def issue_token(user: AuthUser) -> str:
    expires_at = datetime.utcnow() + timedelta(hours=max(1, settings.auth_token_ttl_hours))
    payload = {
        "sub": user.username,
        "role": user.role,
        "exp": int(expires_at.timestamp()),
    }
    body = _b64_json(payload)
    signature = hmac.new(settings.auth_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def parse_token(token: str) -> AuthUser | None:
    try:
        body, raw_signature = token.split(".", 1)
        expected = hmac.new(settings.auth_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        padded_signature = raw_signature + "=" * (-len(raw_signature) % 4)
        signature = base64.urlsafe_b64decode(padded_signature.encode("ascii"))
        if not hmac.compare_digest(signature, expected):
            return None
        payload = _unb64_json(body)
        if int(payload.get("exp") or 0) < int(datetime.utcnow().timestamp()):
            return None
        username = str(payload.get("sub") or "")
        role = str(payload.get("role") or "")
        if not username or role not in {"root", "guest"}:
            return None
        return AuthUser(username=username, role=role)  # type: ignore[arg-type]
    except Exception:
        return None


def current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user = parse_token(authorization.split(" ", 1)[1].strip())
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    return user


def require_root(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "root":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要 root 权限")
    return user


def can_access_task(user: AuthUser, owner_username: str | None) -> bool:
    if user.role == "root":
        return True
    return bool(owner_username) and owner_username == user.username
