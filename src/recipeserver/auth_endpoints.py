"""OIDC login, callback and logout orchestration.

These three endpoints share the same sequence: decide whether auth is enabled,
drive the session helpers, and hand the handler a small set of actions (a
redirect, cookie headers, or a non-leaking error page). The handler owns the
HTTP response; this module owns the login flow decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from ._logger import logger
from .oidc import FLOW_TTL_SECONDS, OIDCError
from .session import FLOW_COOKIE, SESSION_COOKIE, clear_cookie_header, cookie_header, parse_cookies


@dataclass(frozen=True)
class AuthAction:
    """What an auth endpoint wants the HTTP handler to do.

    ``None`` from a decision function means authentication is disabled and the
    endpoint does not exist in this installation.
    """

    redirect: str | None = None
    cookie: tuple[str, str, int] | None = None
    clear_cookie: str | None = None
    error: tuple[int, str, str] | None = None
    error_json: bool = False
    success: bool = False


def begin_login(auth, path: str) -> AuthAction | None:
    if auth is None or not auth.enabled:
        return None
    next_values = parse_qs(urlsplit(path).query).get("next", [])
    try:
        location, cookie = auth.begin_login(next_values[0] if next_values else "/")
    except OIDCError as exc:
        logger.warning(f"Unable to start OIDC login: {exc.detail or exc.message}")
        return AuthAction(error=(503, "Sign-in unavailable", "Sign-in is temporarily unavailable."))
    return AuthAction(redirect=location, cookie=(FLOW_COOKIE, cookie, FLOW_TTL_SECONDS))


def finish_login(auth, path: str, headers) -> AuthAction | None:
    if auth is None or not auth.enabled:
        return None
    params = parse_qs(urlsplit(path).query)
    flow_cookie = parse_cookies(headers.get("Cookie")).get(FLOW_COOKIE)
    # The flow cookie is single-use: clear it even when the callback fails.
    cleared = clear_cookie_header(FLOW_COOKIE, secure=bool(auth.settings.secure_cookies))
    try:
        _session, cookie, return_to = auth.finish_login(params, flow_cookie)
    except OIDCError as exc:
        logger.warning(f"OIDC login failed: {exc.detail or exc.message}")
        return AuthAction(error=(400, "Sign-in failed", exc.message), clear_cookie=cleared)
    lifetime = auth.settings.session_lifetime_minutes * 60
    return AuthAction(redirect=return_to, cookie=(SESSION_COOKIE, cookie, lifetime), clear_cookie=cleared)


def logout(auth, identity, headers) -> AuthAction | None:
    if auth is None or not auth.enabled:
        return None
    if identity is not None and not auth.csrf_ok(headers, identity):
        return AuthAction(error=(403, "Invalid CSRF token", "Invalid CSRF token"), error_json=True)
    cleared = clear_cookie_header(SESSION_COOKIE, secure=bool(auth.settings.secure_cookies))
    return AuthAction(clear_cookie=cleared, success=True)


def queue_cookie_header(auth, cookie: tuple[str, str, int]) -> str:
    """Render a Set-Cookie header using the live auth configuration."""
    name, value, max_age = cookie
    return cookie_header(name, value, max_age, secure=bool(auth and auth.settings.secure_cookies))
