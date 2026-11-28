"""Retention policy vocabulary and the provider contract (leaf module).

Configuration and retention both need this vocabulary, but neither should own
it: putting it here keeps `config.py` from importing the background scheduler
and keeps `retention.py` from importing the configuration class. The provider
is a zero-argument reader so the manager can poll a live configuration without
holding a reference to a particular configuration implementation.
"""

from __future__ import annotations

from collections.abc import Callable

from ._logger import logger

RETENTION_POLICY_GFS = "gfs"
RETENTION_POLICY_UNLIMITED = "unlimited"
DEFAULT_RETENTION_POLICY = RETENTION_POLICY_GFS
RETENTION_POLICIES = (RETENTION_POLICY_GFS, RETENTION_POLICY_UNLIMITED)

# Human-readable labels for the configuration UI, keyed by policy.
RETENTION_POLICY_LABELS = {
    RETENTION_POLICY_GFS: "GFS (recommended)",
    RETENTION_POLICY_UNLIMITED: "Unlimited",
}


def normalize_retention_policy(value: object) -> str:
    """Normalize a retention policy value to ``gfs`` or ``unlimited``.

    Unrecognized or blank values fall back to the documented default (GFS), so
    an existing installation with no policy key migrates to GFS.
    """
    text = str(value or "").strip().lower()
    if text in RETENTION_POLICIES:
        return text
    if text:
        logger.warning(f"Unrecognized timeline retention policy {value!r}; using {DEFAULT_RETENTION_POLICY!r}")
    return DEFAULT_RETENTION_POLICY


def policy_provider(config: object) -> Callable[[], object]:
    """Return a reader of the live ``timeline_retention`` value on *config*.

    The reader is duck-typed on purpose: the configuration module owns the
    attribute, and this leaf module only defines how it is read.
    """
    return lambda: getattr(config, "timeline_retention", DEFAULT_RETENTION_POLICY)
