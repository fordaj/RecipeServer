"""Identity, permissions, and the centralized request gate.

Authentication answers "who is calling"; authorization answers "what may they
do". The three permissions are ``None`` (no access), ``View`` (browse/search),
and ``Edit`` (create/modify/delete). Owner is a separate administrative
privilege, not a fourth permission level.

Every route is classified here so enforcement cannot be forgotten in an
individual handler. The handler calls :meth:`AuthManager.decide` before any API
dispatch or static-file response, including ``HEAD``.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from urllib.parse import quote, urlsplit

from platformdirs import user_data_path

from ._logger import logger
from .auth_config import AuthSettings
from .oidc import OIDCError, OIDCClient, new_login_flow, read_login_flow
from .session import SESSION_COOKIE, Session, create_session, read_session

ACCESS_SETTINGS_FILENAME = "access-settings.json"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/favicon.ico",
        "/api/auth/status",
        "/api/auth/login",
        "/api/auth/callback",
        "/api/auth/logout",
    }
)
PUBLIC_PREFIXES = ("/assets/",)
OWNER_PATHS = frozenset({"/api/config", "/api/config/test-transcription", "/api/auth/settings"})
# Feedback is part of browsing: View users may rate and comment, but cannot
# change any other front matter. Dictation and Markdown rendering are also
# read-only in effect, so they stay available at View level.
VIEW_MUTATION_PATHS = frozenset({"/api/metadata/comments", "/api/metadata/ratings", "/api/transcribe", "/api/assistant-markdown"})


class Permission(IntEnum):
    NONE = 0
    VIEW = 1
    EDIT = 2

    @classmethod
    def parse(cls, value: str) -> Permission:
        normalized = str(value).strip().lower()
        for level in cls:
            if level.name.lower() == normalized:
                return level
        raise ValueError(f"Permission must be one of: {', '.join(level.name.lower() for level in cls)}")

    @property
    def label(self) -> str:
        return self.name.lower()


class Required(Enum):
    PUBLIC = "public"
    VIEW = "view"
    EDIT = "edit"
    OWNER = "owner"


class Decision(Enum):
    ALLOW = "allow"
    LOGIN = "login"
    DENY = "deny"


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    identity: Session | None = None


def required_access(path: str, method: str) -> Required:
    """Classify one request path and method for authorization."""
    path = path.rstrip("/") or "/"
    if path.startswith(PUBLIC_PREFIXES) or path in PUBLIC_PATHS:
        return Required.PUBLIC
    if path in OWNER_PATHS:
        return Required.OWNER
    if method.upper() in MUTATING_METHODS:
        return Required.VIEW if path.rstrip("/") in VIEW_MUTATION_PATHS else Required.EDIT
    return Required.VIEW


@dataclass(frozen=True)
class AccessSettings:
    """Persisted defaults for anonymous and authenticated visitors."""

    guest: Permission = Permission.VIEW
    authenticated: Permission = Permission.VIEW

    def to_json(self) -> dict[str, str]:
        return {"guest": self.guest.label, "authenticated": self.authenticated.label}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> AccessSettings:
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
            return cls(guest=Permission.parse(data.get("guest", "view")), authenticated=Permission.parse(data.get("authenticated", "view")))
        except OSError, ValueError, TypeError:
            logger.warning(f"Ignoring invalid access settings at {path}; using defaults")
            return cls()


class AuthManager:
    """Owns OIDC login, signed sessions, permissions, and the request gate."""

    def __init__(
        self,
        settings: AuthSettings,
        *,
        oidc_client: OIDCClient | None = None,
        access_path: Path | None = None,
        access_settings: AccessSettings | None = None,
    ):
        self.settings = settings
        self.oidc = oidc_client or OIDCClient(settings)
        self.access_path = access_path or user_data_path("recipe-server", appauthor=False) / ACCESS_SETTINGS_FILENAME
        self.access = access_settings or AccessSettings.load(self.access_path)
        if settings.enabled:
            # Fail closed before the HTTP listener opens: a provider that cannot
            # be reached at startup must not silently turn authentication off.
            self.oidc.discover()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    @property
    def secret(self) -> str:
        return self.settings.session_secret

    def identity(self, cookies: dict[str, str]) -> Session | None:
        if not self.enabled:
            return None
        return read_session(cookies.get(SESSION_COOKIE, ""), self.secret)

    def is_owner(self, identity: Session | None) -> bool:
        return bool(identity and identity.subject == self.settings.owner_sub and identity.issuer == self.settings.issuer)

    def permission(self, identity: Session | None) -> Permission:
        if not self.enabled:
            # Disabled auth preserves RecipeServer's historical open access.
            return Permission.EDIT
        if identity is None:
            return self.access.guest
        if self.is_owner(identity):
            return Permission.EDIT
        return self.access.authenticated

    def decide(self, path: str, method: str, headers, cookies: dict[str, str]) -> GateResult:
        """Decide whether a request may proceed."""
        if not self.enabled:
            return GateResult(Decision.ALLOW)
        identity = self.identity(cookies)
        required = required_access(path, method)
        if required is Required.PUBLIC:
            return GateResult(Decision.ALLOW, identity)

        permission = self.permission(identity)
        authorized = {
            Required.VIEW: permission >= Permission.VIEW,
            Required.EDIT: permission >= Permission.EDIT,
            Required.OWNER: self.is_owner(identity),
        }[required]
        if not authorized:
            decision = Decision.LOGIN if identity is None else Decision.DENY
            return GateResult(decision, identity)

        if method.upper() in MUTATING_METHODS and not self.csrf_ok(headers, identity):
            logger.warning(f"Rejected cross-origin or missing-CSRF {method} request to {path}")
            return GateResult(Decision.DENY, identity)
        return GateResult(Decision.ALLOW, identity)

    def csrf_ok(self, headers, identity: Session | None) -> bool:
        """Reject cross-site mutations; require a session token when signed in."""
        if (headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
            return False
        origin = headers.get("Origin")
        if origin:
            origin_host = urlsplit(origin).hostname
            host_header = headers.get("Host") or ""
            request_host = urlsplit("//" + host_header).hostname
            if origin_host not in {request_host, self.settings.redirect_host}:
                return False
        if identity is not None:
            supplied = headers.get("X-CSRF-Token") or ""
            if not supplied or not hmac.compare_digest(supplied, identity.csrf_token(self.secret)):
                return False
        return True

    def status(self, identity: Session | None) -> dict:
        """The only auth information exposed to the browser (no secrets)."""
        permission = self.permission(identity)
        return {
            "enabled": self.enabled,
            "authenticated": identity is not None,
            "permission": permission.label,
            "canEdit": permission >= Permission.EDIT,
            "isOwner": self.is_owner(identity),
            "name": identity.name if identity else None,
            "csrfToken": identity.csrf_token(self.secret) if identity else None,
            "loginUrl": self.settings.login_url,
            "logoutUrl": "/api/auth/logout",
            "callbackPath": self.settings.callback_path,
        }

    def begin_login(self, return_to: str) -> tuple[str, str]:
        """Return ``(provider authorization URL, signed flow cookie)``."""
        flow, cookie, challenge = new_login_flow(self.secret, return_to)
        location = self.oidc.authorization_url(flow["state"], flow["nonce"], challenge)
        return location, cookie

    def finish_login(self, params: dict[str, list[str]], flow_cookie: str | None) -> tuple[Session, str, str]:
        """Validate the callback, verify the ID token, and mint a session."""
        provider_error = params.get("error", [None])[0]
        if provider_error:
            raise OIDCError("The identity provider denied the sign-in")
        flow = read_login_flow(flow_cookie, self.secret)
        if flow is None:
            raise OIDCError("The sign-in session has expired; please try again")
        state = params.get("state", [None])[0]
        if not state or not hmac.compare_digest(state, flow["state"]):
            raise OIDCError("The sign-in state did not match; please try again")
        code = params.get("code", [None])[0]
        if not code:
            raise OIDCError("The identity provider did not return an authorization code")
        id_token = self.oidc.exchange_code(code, flow["verifier"])
        issuer, subject, name = self.oidc.verify_id_token(id_token, flow["nonce"])
        cookie, session = create_session(issuer, subject, name, self.secret, self.settings.session_lifetime_minutes)
        return session, cookie, flow["next"]

    def update_access(self, guest: Permission, authenticated: Permission) -> None:
        """Owner-only change to the persisted default permissions."""
        self.access = AccessSettings(guest=guest, authenticated=authenticated)
        self.access.save(self.access_path)
        logger.info(f"Access settings saved (guest={guest.label}, authenticated={authenticated.label})")

    def login_url(self, return_to: str) -> str:
        return f"{self.settings.login_url}?next={quote(return_to, safe='/')}"
