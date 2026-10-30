"""Signed cookies and PKCE helpers for the optional "Sign in with Lichess" flow.

The session cookie holds only the signed user id. The OAuth access token is used once to
read the account, then revoked.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

LICHESS_HOST = "https://lichess.org"
SESSION_COOKIE = "cca_session"
OAUTH_COOKIE = "cca_oauth"
SESSION_MAX_AGE = 30 * 24 * 3600
OAUTH_MAX_AGE = 10 * 60

_dev_secret: str | None = None


def session_secret() -> bytes:
    global _dev_secret
    configured = os.getenv("SESSION_SECRET", "").strip()
    if configured:
        return configured.encode()
    if _dev_secret is None:
        _dev_secret = secrets.token_urlsafe(32)
        logger.warning(
            "SESSION_SECRET is not set; using a random per-process secret. "
            "Sign-ins will not survive a restart."
        )
    return _dev_secret.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(purpose: str, body: str) -> str:
    mac = hmac.new(session_secret(), f"{purpose}.{body}".encode(), hashlib.sha256)
    return _b64(mac.digest())


def sign(payload: dict, purpose: str) -> str:
    body = _b64(json.dumps({**payload, "iat": int(time.time())}, separators=(",", ":")).encode())
    return f"{body}.{_signature(purpose, body)}"


def unsign(token: str | None, purpose: str, max_age: int) -> dict | None:
    if not token or "." not in token:
        return None
    body, _, signature = token.rpartition(".")
    if not hmac.compare_digest(signature, _signature(purpose, body)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or time.time() - payload.get("iat", 0) > max_age:
        return None
    return payload


def session_user_id(token: str | None) -> str | None:
    session = unsign(token, "session", SESSION_MAX_AGE)
    user_id = session.get("uid") if session else None
    return user_id if isinstance(user_id, str) else None


def chesscom_code(user_id: str, username: str) -> str:
    """The code a user puts on their Chess.com profile. Derived, so nothing needs storing."""
    digest = _signature("chesscom", f"{user_id}.{username.strip().lower()}")
    return "coach-" + digest.replace("-", "").replace("_", "")[:12]


def new_code_verifier() -> str:
    return secrets.token_urlsafe(48)


def code_challenge(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def safe_next(value: str | None) -> str:
    """Allow only same-origin relative paths such as /games?x=1."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or any(ord(ch) < 32 for ch in value):
        return "/"
    return value
