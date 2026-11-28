"""Configuration payloads and live settings live outside the HTTP handler."""

from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from recipeserver import config_endpoints
from recipeserver.config_defaults import DEFAULT_DICTATION_ENABLED, DEFAULT_TRANSCRIPTION_ENDPOINT, DEFAULT_TRANSCRIPTION_MODEL


def test_dictation_enabled_and_transcription_settings_fall_back():
    assert config_endpoints.dictation_enabled(None) is DEFAULT_DICTATION_ENABLED
    assert config_endpoints.dictation_enabled(SimpleNamespace(dictation_enabled=False)) is False
    assert config_endpoints.transcription_settings(None) == {
        "endpoint": DEFAULT_TRANSCRIPTION_ENDPOINT,
        "model": DEFAULT_TRANSCRIPTION_MODEL,
        "keep_alive": "0",
    }
    config = SimpleNamespace(transcription_endpoint="http://x", transcription_model="m", transcription_keep_alive="-1")
    assert config_endpoints.transcription_settings(config)["keep_alive"] == "-1"


def test_config_payload_only_exposes_config_fields(monkeypatch):
    monkeypatch.setattr(config_endpoints.ai_recipe, "model_info", lambda endpoint, name: {"present": False})
    config = SimpleNamespace(
        get_config_values=lambda: {"food_color": "#8d5542"},
        field_specs=lambda: [{"key": "food_color"}],
        model_endpoint="",
        transcription_endpoint="",
    )
    payload = config_endpoints.config_payload(config)

    assert set(payload) == {"values", "fields", "models"}
    assert "auth_enabled" not in json.dumps(payload)
    with pytest.raises(ValueError, match="Configuration is not available"):
        config_endpoints.config_payload(None)


def test_apply_config_payload_parses_and_returns_current_values():
    class Config:
        def apply_config_values(self, values):
            assert values == {"food_color": "#abcdef"}
            return ["food_color"]

        def get_config_values(self):
            return {"food_color": "#abcdef"}

    body = json.dumps({"values": {"food_color": "#abcdef"}}).encode("utf-8")
    headers = {"Content-Length": str(len(body))}
    changed, values = config_endpoints.apply_config_payload(Config(), BytesIO(body), headers, 1000)

    assert changed == ["food_color"]
    assert values == {"food_color": "#abcdef"}
