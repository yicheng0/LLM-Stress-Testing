from __future__ import annotations

import argparse
import base64
import hashlib
import secrets


def hash_password(password: str, *, iterations: int = 260_000) -> str:
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    encoded = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a PBKDF2 password hash for auth_users.json")
    parser.add_argument("password", help="Plain text password to hash")
    args = parser.parse_args()
    print(hash_password(args.password))


if __name__ == "__main__":
    main()
