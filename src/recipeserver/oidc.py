"""Provider-agnostic OIDC authorization-code flow with PKCE.

Discovery supplies the endpoints and JWKS; ID tokens are verified with a vetted
JWT library (signature, ``iss``, ``aud``, ``exp``) and the app checks ``nonce``
and a non-empty ``sub`` itself. No provider-specific code is used.

The short-lived login flow (state, nonce, PKCE verifier, return URL) travels in
a signed, single-use cookie rather than a server-side store, matching the
database-free design. State is compared in constant time and the flow cookie is
cleared on the callback whether login succeeds or fails.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import jwt

from ._logger import logger
from .auth_config import AuthSettings
from .session import sign_payload, verify_payload

HTTP_TIMEOUT_SECONDS = 10
FLOW_TTL_SECONDS = 10 * 60
# All asymmetric algorithms a conforming provider may use for ID tokens.
ID_TOKEN_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "EdDSA")
DISCOVERY_SUFFIX = "/.well-known/openid-configuration"


class OIDCError(Exception):
    """An authentication failure with a public message and a private detail."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _safe_detail(text: str) -> str:
    """Keep provider error bodies out of logs beyond one short line."""
    return text.strip().splitlines()[0][:300] if text.strip() else ""


def _request_json(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, data=data, headers=headers or {})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read(1024 * 1024)
    except HTTPError as exc:
        detail = _safe_detail(exc.read(4096).decode("utf-8", errors="replace"))
        raise OIDCError("The identity provider rejected the request", detail) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise OIDCError("Unable to contact the identity provider", str(exc)) from None
    try:
        parsed = json.loads(body)
    except ValueError, UnicodeDecodeError:
        raise OIDCError("The identity provider returned an invalid response") from None
    if not isinstance(parsed, dict):
        raise OIDCError("The identity provider returned an invalid response")
    return parsed


class OIDCClient:
    """Discovers and talks to one configured OIDC provider."""

    def __init__(self, settings: AuthSettings):
        self.settings = settings
        self._discovery: dict | None = None
        self._jwks_client: jwt.PyJWKClient | None = None

    def discover(self) -> None:
        """Fetch discovery and JWKS client; fail closed on any problem."""
        document = _request_json(self.settings.issuer.rstrip("/") + DISCOVERY_SUFFIX)
        issuer = document.get("issuer")
        if not isinstance(issuer, str) or issuer != self.settings.issuer:
            raise OIDCError("The identity provider issuer does not match the configured issuer", f"discovery issuer: {issuer!r}")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(document.get(key), str) or not document[key]:
                raise OIDCError("The identity provider discovery document is incomplete", f"missing {key}")
        self._discovery = document
        self._jwks_client = jwt.PyJWKClient(document["jwks_uri"], timeout=HTTP_TIMEOUT_SECONDS)
        logger.info(f"OIDC discovery succeeded for {self.settings.issuer!r}")

    @property
    def _endpoints(self) -> dict:
        if self._discovery is None:
            raise OIDCError("OIDC discovery has not completed")
        return self._discovery

    def authorization_url(self, state: str, nonce: str, challenge: str) -> str:
        """Build the provider authorize URL for a new login attempt."""
        params = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._endpoints['authorization_endpoint']}?{urlencode(params)}"

    def exchange_code(self, code: str, verifier: str) -> str:
        """Exchange an authorization code for a raw ID token."""
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri,
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "code_verifier": verifier,
            }
        ).encode("utf-8")
        response = _request_json(
            self._endpoints["token_endpoint"],
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        id_token = response.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise OIDCError("The identity provider did not return an ID token")
        return id_token

    def verify_id_token(self, id_token: str, nonce: str) -> tuple[str, str, str]:
        """Verify the ID token and return ``(issuer, subject, display name)``."""
        if self._jwks_client is None:
            raise OIDCError("OIDC discovery has not completed")
        try:
            key = self._jwks_client.get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(
                id_token,
                key,
                algorithms=list(ID_TOKEN_ALGORITHMS),
                audience=self.settings.client_id,
                issuer=self.settings.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                leeway=30,
            )
        except Exception as exc:
            # PyJWT messages can describe tokens; only log a short summary.
            raise OIDCError("The identity token could not be verified", _safe_detail(str(exc))) from None
        if claims.get("nonce") != nonce:
            raise OIDCError("The identity token nonce did not match")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OIDCError("The identity token has no subject")
        name = claims.get("name") or claims.get("preferred_username") or claims.get("email") or ""
        return claims["iss"], subject, name if isinstance(name, str) else ""


def new_login_flow(secret: str, return_to: str) -> tuple[dict, str, str]:
    """Return ``(flow, signed cookie, S256 challenge)`` for a new login."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    flow = {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "next": safe_return_to(return_to),
        "exp": int(time.time()) + FLOW_TTL_SECONDS,
    }
    return flow, sign_payload(flow, secret), challenge


def read_login_flow(cookie: str | None, secret: str) -> dict | None:
    """Read and expire-check a signed login flow cookie."""
    payload = verify_payload(cookie or "", secret)
    if payload is None or not isinstance(payload.get("state"), str) or not isinstance(payload.get("nonce"), str):
        return None
    if not isinstance(payload.get("verifier"), str) or not isinstance(payload.get("exp"), int):
        return None
    if payload["exp"] <= int(time.time()):
        return None
    return payload


def safe_return_to(value: str | None) -> str:
    """Only allow same-origin relative paths as a post-login destination."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if any(character in value for character in ("\\", "\r", "\n", "\x00")):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or value.startswith("/api/auth/"):
        return "/"
    return value
