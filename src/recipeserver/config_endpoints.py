"""Configuration API domain operations.

The handler owns routing and response codes; this module owns reading the
configuration into the dialog's payload, probing the configured models, and
applying an edited payload (including the live settings the transcription and
dictation endpoints need).
"""

from __future__ import annotations

from . import ai_recipe
from .config_defaults import (
    DEFAULT_DICTATION_ENABLED,
    DEFAULT_KEEP_ALIVE_MINUTES,
    DEFAULT_TRANSCRIPTION_ENDPOINT,
    DEFAULT_TRANSCRIPTION_MODEL,
)
from .request_payload import read_json_payload


def dictation_enabled(config) -> bool:
    """Report whether the browser should offer dictation."""
    return getattr(config, "dictation_enabled", DEFAULT_DICTATION_ENABLED) if config is not None else DEFAULT_DICTATION_ENABLED


def transcription_settings(config) -> dict:
    """Resolve the Ollama transcription settings for a request.

    Reads the live configuration, falling back to the documented defaults when
    keys (or the whole configuration, as in some tests) are missing.
    """
    return {
        "endpoint": getattr(config, "transcription_endpoint", "") or DEFAULT_TRANSCRIPTION_ENDPOINT,
        "model": getattr(config, "transcription_model", "") or DEFAULT_TRANSCRIPTION_MODEL,
        "keep_alive": getattr(config, "transcription_keep_alive", "") or DEFAULT_KEEP_ALIVE_MINUTES,
    }


def probe_configured_models(config) -> dict:
    """Best-effort installation metadata for the three configured models."""
    if config is None:
        return {}
    ai_endpoint = getattr(config, "model_endpoint", "") or ""
    transcription_endpoint = getattr(config, "transcription_endpoint", "") or DEFAULT_TRANSCRIPTION_ENDPOINT
    return {
        "all_purpose_model_name": ai_recipe.model_info(ai_endpoint, getattr(config, "all_purpose_model_name", "")),
        "image_analysis_model": ai_recipe.model_info(ai_endpoint, getattr(config, "image_analysis_model", "")),
        "transcription_model": ai_recipe.model_info(transcription_endpoint, getattr(config, "transcription_model", "")),
    }


def config_payload(config) -> dict:
    """The `GET /api/config` response body; auth keys are never included."""
    if config is None:
        raise ValueError("Configuration is not available")
    return {
        "values": config.get_config_values(),
        "fields": config.field_specs(),
        "models": probe_configured_models(config),
    }


def apply_config_payload(config, rfile, headers, max_size: int) -> tuple[list[str], dict]:
    """Validate and apply an edited payload; return changed keys and new values."""
    payload = read_json_payload(rfile, headers, max_size)
    if config is None:
        raise ValueError("Configuration is not available")
    changed = config.apply_config_values(payload.get("values"))
    return changed, config.get_config_values()
