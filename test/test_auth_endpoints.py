"""OIDC login/callback/logout decisions without an HTTP handler."""

from __future__ import annotations

from types import SimpleNamespace

from recipeserver import auth_endpoints
from recipeserver.auth_endpoints import begin_login, finish_login, logout, queue_cookie_header
from recipeserver.oidc import FLOW_TTL_SECONDS
from recipeserver.session import FLOW_COOKIE, SESSION_COOKIE


class _Auth:
    def __init__(self, *, enabled=True, fail=False) -> None:
        self.enabled = enabled
        self.fail = fail
        self.settings = SimpleNamespace(secure_cookies=False, session_lifetime_minutes=12)
        self.csrf_ok_calls = []

    def begin_login(self, return_to):
        if self.fail:
            from recipeserver.oidc import OIDCError

            raise OIDCError("provider down", detail="timeout")
        return "https://provider.example.com/authorize", "flow-cookie"

    def finish_login(self, params, flow_cookie):
        if self.fail:
            from recipeserver.oidc import OIDCError

            raise OIDCError("bad code")
        return None, "session-cookie", params.get("next", ["/"])[0]

    def csrf_ok(self, headers, identity):
        self.csrf_ok_calls.append((headers, identity))
        return True


def test_disabled_auth_endpoints_do_not_exist():
    disabled = _Auth(enabled=False)
    assert begin_login(disabled, "/api/auth/login") is None
    assert finish_login(disabled, "/api/auth/callback?code=x", {}) is None
    assert logout(disabled, None, {}) is None


def test_begin_login_redirects_with_a_single_use_flow_cookie():
    action = begin_login(_Auth(), "/api/auth/login?next=%2Findex.html")
    assert action.redirect == "https://provider.example.com/authorize"
    assert action.cookie == (FLOW_COOKIE, "flow-cookie", FLOW_TTL_SECONDS)
    assert action.error is None


def test_begin_login_failure_is_a_non_leaking_error_page():
    action = begin_login(_Auth(fail=True), "/api/auth/login")
    assert action.error == (503, "Sign-in unavailable", "Sign-in is temporarily unavailable.")
    assert "timeout" not in str(action)


def test_finish_login_clears_flow_cookie_even_on_failure():
    headers = {"Cookie": "rs_oidc_flow=flow-cookie"}
    success = finish_login(_Auth(), "/api/auth/callback?code=x&next=%2F", headers)
    assert success.redirect == "/"
    assert success.cookie[0] == SESSION_COOKIE
    assert success.clear_cookie is not None

    failed = finish_login(_Auth(fail=True), "/api/auth/callback?code=bad", headers)
    assert failed.error[0] == 400
    assert failed.clear_cookie is not None
    assert failed.cookie is None


def test_logout_requires_csrf_and_clears_the_session_cookie():
    auth = _Auth()
    action = logout(auth, "identity", {"X-CSRF-Token": "t"})
    assert action.success is True
    assert action.clear_cookie is not None
    assert auth.csrf_ok_calls

    auth.csrf_ok = lambda headers, identity: False
    denied = logout(auth, "identity", {})
    assert denied.error == (403, "Invalid CSRF token", "Invalid CSRF token")
    assert denied.error_json is True
    assert denied.clear_cookie is None


def test_queue_cookie_header_uses_the_live_secure_setting():
    header = queue_cookie_header(_Auth(), (SESSION_COOKIE, "value", 60))
    assert SESSION_COOKIE in header
    assert "Max-Age=60" in header
    assert "Secure" not in header
