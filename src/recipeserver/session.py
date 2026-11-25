"""Stateless signed cookies for authentication and login flows.

Sessions are self-contained: the cookie carries the minimal identity, an
expiry, and a nonce; an HMAC proves it was issued by this server. There is no
session store, so a logout only expires the cookie in that browser and an
already-issued cookie cannot be revoked individually. Rotating the signing
secret invalidates every session at once (see :mod:`auth_config`).

Cookies are ``HttpOnly`` and ``SameSite=Lax`` (Strict would drop the state
cookie on the top-level redirect back from the identity provider). ``Secure``
is set when the configured redirect URI is HTTPS. Mutations are additionally
protected by a per-session CSRF token and Origin checks in :mod:`auth`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

SESSION_COOKIE = "rs_session"
FLOW_COOKIE = "rs_oidc_flow"
COOKIE_MAX_AGE_LABEL = "Max-Age"


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_payload(payload: dict, secret: str) -> str:
    """Return ``base64url(json).base64url(HMAC-SHA256)`` for *payload*."""
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_payload(value: str, secret: str) -> dict | None:
    """Decode and verify a signed payload, returning ``None`` if invalid."""
    if not value or value.count(".") != 1:
        return None
    body, signature = value.split(".", 1)
    expected = _b64encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except ValueError, UnicodeDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class Session:
    """The verified contents of a session cookie."""

    issuer: str
    subject: str
    name: str
    nonce: str
    expires: int

    @property
    def key(self) -> tuple[str, str]:
        """Stable identity key: issuer + subject."""
        return self.issuer, self.subject

    def csrf_token(self, secret: str) -> str:
        """Per-session CSRF token derived from the signed nonce."""
        digest = hmac.new(secret.encode("utf-8"), f"csrf:{self.nonce}".encode("utf-8"), hashlib.sha256).digest()
        return _b64encode(digest)


def create_session(issuer: str, subject: str, name: str, secret: str, lifetime_minutes: int) -> tuple[str, Session]:
    """Return ``(cookie_value, session)`` for a freshly authenticated user."""
    now = int(time.time())
    payload = {
        "v": 1,
        "iss": issuer,
        "sub": subject,
        "name": name or "",
        "nonce": _b64encode(secrets.token_bytes(24)),
        "iat": now,
        "exp": now + lifetime_minutes * 60,
    }
    session = Session(
        issuer=payload["iss"],
        subject=payload["sub"],
        name=payload["name"],
        nonce=payload["nonce"],
        expires=payload["exp"],
    )
    return sign_payload(payload, secret), session


def read_session(value: str, secret: str) -> Session | None:
    """Verify a session cookie and enforce its embedded expiry."""
    payload = verify_payload(value, secret)
    if payload is None or payload.get("v") != 1:
        return None
    issuer, subject = payload.get("iss"), payload.get("sub")
    nonce = payload.get("nonce")
    expires = payload.get("exp")
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        return None
    if not isinstance(nonce, str) or not nonce or not isinstance(expires, int) or expires <= int(time.time()):
        return None
    name = payload.get("name", "")
    return Session(issuer=issuer, subject=subject, name=name if isinstance(name, str) else "", nonce=nonce, expires=expires)


def cookie_header(name: str, value: str, max_age: int, *, secure: bool) -> str:
    """Build a session/flow ``Set-Cookie`` header."""
    parts = [
        f"{name}={value}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"{COOKIE_MAX_AGE_LABEL}={max_age}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie_header(name: str, *, secure: bool) -> str:
    """Build a ``Set-Cookie`` header that removes *name*."""
    return cookie_header(name, "", 0, secure=secure)


def parse_cookies(header: str | None) -> dict[str, str]:
    """Parse a ``Cookie`` header into a name/value mapping."""
    cookies: dict[str, str] = {}
    for part in (header or "").split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    return cookies
