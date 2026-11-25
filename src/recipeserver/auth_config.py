"""Optional authentication configuration.

Authentication is off by default. Every setting can be supplied three ways, in
this precedence order:

1. an environment variable, when it is explicitly present;
2. a key in ``recipe-server-cfg.toml``;
3. an application default.

The TOML keys are deliberately *not* ``ConfigField`` entries: ``GET /api/config``
returns every ``ConfigField`` value to the browser, and ``POST /api/config``
rewrites the TOML file from that same list. Keeping auth keys out of that list
means client secrets and the signing secret are never served with the site and
cannot be injected through the configuration API. :mod:`config` still preserves
them verbatim when it writes the file.

The session signing secret is persistent: when neither the environment nor the
TOML file supplies one, a random secret is generated once and stored in the
user-data directory. Sessions therefore survive a restart, and rotating the
secret (in either place) invalidates every existing session.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_path

from ._logger import logger

# The callback path is fixed so it can be registered as a normal API route and
# validated against OIDC_REDIRECT_URI at startup.
CALLBACK_PATH = "/api/auth/callback"
SESSION_SECRET_FILENAME = "session-secret"
SESSION_SECRET_MIN_LENGTH = 16
DEFAULT_SESSION_LIFETIME_MINUTES = 12 * 60
MIN_SESSION_LIFETIME_MINUTES = 1
MAX_SESSION_LIFETIME_MINUTES = 30 * 24 * 60

# Env var -> TOML key. The TOML keys are intentionally snake_case and prefixed
# so they are obvious to a human editing the file.
SETTING_KEYS: tuple[tuple[str, str], ...] = (
    ("AUTH_ENABLED", "auth_enabled"),
    ("OIDC_ISSUER", "oidc_issuer"),
    ("OIDC_CLIENT_ID", "oidc_client_id"),
    ("OIDC_CLIENT_SECRET", "oidc_client_secret"),
    ("OIDC_REDIRECT_URI", "oidc_redirect_uri"),
    ("OIDC_OWNER_SUB", "oidc_owner_sub"),
    ("SESSION_SECRET", "session_secret"),
    ("SESSION_LIFETIME_MINUTES", "session_lifetime_minutes"),
)
AUTH_TOML_KEYS = frozenset(toml_key for _env, toml_key in SETTING_KEYS)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class AuthSettings:
    """Validated settings for the optional OIDC gate."""

    enabled: bool
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    owner_sub: str = ""
    session_secret: str = ""
    session_lifetime_minutes: int = DEFAULT_SESSION_LIFETIME_MINUTES
    callback_path: str = CALLBACK_PATH

    @property
    def secure_cookies(self) -> bool:
        """Set ``Secure`` when the external redirect URI is HTTPS."""
        return urlsplit(self.redirect_uri).scheme == "https"

    @property
    def redirect_host(self) -> str:
        """Host (without port) of the externally visible redirect URI."""
        return urlsplit(self.redirect_uri).hostname or ""

    @property
    def login_url(self) -> str:
        return "/api/auth/login"


class AuthConfigError(ValueError):
    """Raised when authentication is enabled but misconfigured."""


def _parse_bool(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise AuthConfigError(f"{label} must be true or false, not {value!r}")


def _is_loopback(host: str) -> bool:
    return host.lower() in {"localhost", "127.0.0.1", "::1", "[::1]"} or host.lower().endswith(".localhost")


def _validate_http_url(value: str, label: str, *, allow_path: bool, required_path: str = "") -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        raise AuthConfigError(f"{label} must be a valid http:// or https:// URL") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AuthConfigError(f"{label} must be an absolute http:// or https:// URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise AuthConfigError(f"{label} must not contain credentials, a query string, or a fragment")
    if parts.scheme == "http" and not _is_loopback(parts.hostname):
        raise AuthConfigError(f"{label} must use https, except for loopback development URLs")
    if not allow_path and parts.path.strip("/"):
        raise AuthConfigError(f"{label} must not include a path")
    if required_path and parts.path.rstrip("/") != required_path:
        raise AuthConfigError(f"{label} path must be {required_path} (got {parts.path or '/'!r})")
    return value


def _load_or_create_secret(directory: Path) -> str:
    """Return the persistent signing secret, creating it on first use."""
    secret_path = directory / SESSION_SECRET_FILENAME
    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
        if len(secret) >= SESSION_SECRET_MIN_LENGTH:
            return secret
        logger.warning(f"Session secret at {secret_path} is too short; generating a new one")
    secret = secrets.token_urlsafe(48)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(secret + "\n", encoding="utf-8")
    try:
        secret_path.chmod(0o600)
    except OSError:
        # Windows does not expose POSIX permissions; the file still lives in
        # the per-user data directory.
        pass
    logger.info(f"Generated a persistent session secret at {secret_path} (keep this file private)")
    return secret


def load_auth_settings(toml_values: dict[str, str] | None = None, *, secret_directory: Path | None = None) -> AuthSettings:
    """Resolve and validate authentication settings from env, TOML, defaults.

    ``toml_values`` is the raw auth-key subset of the configuration file; it is
    never persisted back from here. ``secret_directory`` exists for tests, so
    a generated signing secret never lands in the developer's real user-data
    directory.
    """
    toml_values = toml_values or {}
    values = {toml_key: os.environ[env_key] if env_key in os.environ else toml_values.get(toml_key, "") for env_key, toml_key in SETTING_KEYS}

    errors: list[str] = []
    try:
        enabled = _parse_bool(values["auth_enabled"] or "false", "auth_enabled")
    except AuthConfigError as exc:
        raise AuthConfigError(str(exc)) from None

    if not enabled:
        logger.info("Authentication is disabled; the site keeps its default open access")
        return AuthSettings(enabled=False)

    # Resolve the secret only when needed so a disabled install creates no file.
    if not values["session_secret"].strip():
        directory = secret_directory or user_data_path("recipe-server", appauthor=False)
        values["session_secret"] = _load_or_create_secret(directory)
    if len(values["session_secret"]) < SESSION_SECRET_MIN_LENGTH:
        errors.append(f"session_secret must be a random value of at least {SESSION_SECRET_MIN_LENGTH} characters")

    for key in ("oidc_issuer", "oidc_client_id", "oidc_client_secret", "oidc_redirect_uri", "oidc_owner_sub"):
        if not str(values[key]).strip():
            errors.append(f"{key} is required when auth_enabled = true")

    lifetime_text = str(values["session_lifetime_minutes"]).strip()
    lifetime = DEFAULT_SESSION_LIFETIME_MINUTES
    if lifetime_text:
        try:
            lifetime = int(lifetime_text)
        except ValueError:
            errors.append("session_lifetime_minutes must be a whole number of minutes")
        else:
            if not MIN_SESSION_LIFETIME_MINUTES <= lifetime <= MAX_SESSION_LIFETIME_MINUTES:
                errors.append(f"session_lifetime_minutes must be between {MIN_SESSION_LIFETIME_MINUTES} and {MAX_SESSION_LIFETIME_MINUTES}")

    if values["oidc_issuer"].strip():
        try:
            _validate_http_url(values["oidc_issuer"].strip(), "oidc_issuer", allow_path=False)
        except AuthConfigError as exc:
            errors.append(str(exc))
    if values["oidc_redirect_uri"].strip():
        try:
            _validate_http_url(
                values["oidc_redirect_uri"].strip(),
                "oidc_redirect_uri",
                allow_path=True,
                required_path=CALLBACK_PATH,
            )
        except AuthConfigError as exc:
            errors.append(str(exc))

    if errors:
        raise AuthConfigError("Invalid authentication configuration: " + "; ".join(sorted(errors)))

    settings = AuthSettings(
        enabled=True,
        issuer=values["oidc_issuer"].strip(),
        client_id=values["oidc_client_id"].strip(),
        client_secret=values["oidc_client_secret"].strip(),
        redirect_uri=values["oidc_redirect_uri"].strip(),
        owner_sub=values["oidc_owner_sub"].strip(),
        session_secret=values["session_secret"].strip(),
        session_lifetime_minutes=lifetime,
    )
    logger.info(
        f"Authentication enabled for issuer {settings.issuer!r}"
        f" (callback {settings.callback_path}, session lifetime {settings.session_lifetime_minutes} minutes)"
    )
    return settings
