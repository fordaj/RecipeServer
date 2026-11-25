import time

from recipeserver.oidc import new_login_flow, read_login_flow, safe_return_to
from recipeserver.session import (
    create_session,
    read_session,
    sign_payload,
    verify_payload,
)

SECRET = "a-long-persistent-signing-secret"


def test_session_roundtrip_carries_identity_and_csrf():
    cookie, session = create_session("https://idp.example.com", "sub-1", "Ada", SECRET, 60)

    parsed = read_session(cookie, SECRET)
    assert parsed is not None
    assert parsed.key == ("https://idp.example.com", "sub-1")
    assert parsed.name == "Ada"
    assert parsed.expires > int(time.time())
    assert session.csrf_token(SECRET) == parsed.csrf_token(SECRET)
    assert len(session.csrf_token(SECRET)) > 20


def test_tampered_and_expired_sessions_are_rejected():
    cookie, _session = create_session("iss", "sub", "", SECRET, 60)
    body, signature = cookie.split(".")
    assert read_session(f"{body[:-2]}xx.{signature}", SECRET) is None
    assert read_session(f"{body}.{signature[:-2]}xx", SECRET) is None
    assert read_session(cookie, "a-different-signing-secret") is None

    expired = sign_payload({"v": 1, "iss": "iss", "sub": "sub", "nonce": "n", "exp": int(time.time()) - 1}, SECRET)
    assert read_session(expired, SECRET) is None
    assert read_session(sign_payload({"v": 2, "iss": "iss", "sub": "sub", "nonce": "n", "exp": int(time.time()) + 60}, SECRET), SECRET) is None


def test_payload_signing_is_authenticated():
    value = sign_payload({"hello": "world"}, SECRET)
    assert verify_payload(value, SECRET) == {"hello": "world"}
    assert verify_payload(value + "tampered", SECRET) is None
    assert verify_payload("no-dot", SECRET) is None


def test_login_flow_is_signed_expiring_and_single_use_in_spirit():
    _flow, cookie, challenge = new_login_flow(SECRET, "/recipes?x=1")
    flow = read_login_flow(cookie, SECRET)

    assert flow is not None
    assert flow["next"] == "/recipes?x=1"
    assert len(flow["state"]) > 20
    assert len(flow["nonce"]) > 20
    assert len(challenge) == 43  # base64url SHA-256, unpadded
    assert read_login_flow(cookie, "another-secret") is None

    expired = sign_payload(
        {"state": "s", "nonce": "n", "verifier": "v", "next": "/", "exp": int(time.time()) - 1},
        SECRET,
    )
    assert read_login_flow(expired, SECRET) is None


def test_safe_return_to_blocks_open_redirects():
    assert safe_return_to("/index.html") == "/index.html"
    for value in ("//evil.example", "https://evil.example", "/\\evil", "/api/auth/login", "javascript:alert(1)", "", None):
        assert safe_return_to(value) == "/"
