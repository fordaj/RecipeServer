import json
import tomllib

import pytest

from recipeserver.auth_config import (
    AUTH_TOML_KEYS,
    SESSION_SECRET_FILENAME,
    SETTING_KEYS,
    AuthConfigError,
    load_auth_settings,
)
from recipeserver.config import CONFIG_FILENAME, Configuration


@pytest.fixture
def clean_env(monkeypatch):
    for env_key, _toml_key in SETTING_KEYS:
        monkeypatch.delenv(env_key, raising=False)


@pytest.fixture
def enabled_toml():
    return {
        "auth_enabled": "true",
        "oidc_issuer": "https://idp.example.com",
        "oidc_client_id": "recipeserver",
        "oidc_client_secret": "top-secret",
        "oidc_redirect_uri": "https://recipes.example.com/api/auth/callback",
        "oidc_owner_sub": "owner-sub",
        "session_secret": "a-long-persistent-signing-secret",
    }


@pytest.mark.usefixtures("clean_env")
def test_auth_is_disabled_by_default(tmp_path):
    settings = load_auth_settings({}, secret_directory=tmp_path)

    assert settings.enabled is False
    assert not (tmp_path / SESSION_SECRET_FILENAME).exists()


@pytest.mark.usefixtures("clean_env")
def test_toml_values_are_used_when_no_environment_variable_is_set(tmp_path, enabled_toml):
    settings = load_auth_settings(enabled_toml, secret_directory=tmp_path)

    assert settings.enabled is True
    assert settings.issuer == "https://idp.example.com"
    assert settings.client_secret == "top-secret"
    assert settings.session_secret == "a-long-persistent-signing-secret"
    assert settings.session_lifetime_minutes == 720
    assert settings.secure_cookies is True
    assert settings.callback_path == "/api/auth/callback"


@pytest.mark.usefixtures("clean_env")
def test_environment_variable_overrides_toml_and_default(tmp_path, enabled_toml, monkeypatch):
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "from-environment")
    monkeypatch.setenv("SESSION_LIFETIME_MINUTES", "45")
    enabled_toml["session_lifetime_minutes"] = "60"

    settings = load_auth_settings(enabled_toml, secret_directory=tmp_path)

    assert settings.client_secret == "from-environment"
    assert settings.session_lifetime_minutes == 45
    # Unset settings still fall through to the TOML value.
    assert settings.client_id == "recipeserver"


@pytest.mark.usefixtures("clean_env")
def test_generated_secret_is_persistent(tmp_path, enabled_toml):
    enabled_toml.pop("session_secret")
    first = load_auth_settings(enabled_toml, secret_directory=tmp_path)
    second = load_auth_settings(enabled_toml, secret_directory=tmp_path)

    assert first.session_secret == second.session_secret
    assert len(first.session_secret) >= 16
    assert (tmp_path / SESSION_SECRET_FILENAME).read_text(encoding="utf-8").strip() == first.session_secret
    assert "top-secret" not in first.session_secret


@pytest.mark.usefixtures("clean_env")
def test_invalid_configuration_fails_closed(tmp_path, enabled_toml):
    enabled_toml["oidc_redirect_uri"] = "https://recipes.example.com/wrong/callback"
    enabled_toml["oidc_issuer"] = "http://idp.example.com"
    enabled_toml["session_secret"] = "short"

    with pytest.raises(AuthConfigError) as error:
        load_auth_settings(enabled_toml, secret_directory=tmp_path)

    message = str(error.value)
    assert "oidc_redirect_uri" in message
    assert "oidc_issuer" in message
    assert "session_secret" in message


@pytest.mark.usefixtures("clean_env")
def test_missing_required_settings_fail_closed(tmp_path):
    with pytest.raises(AuthConfigError) as error:
        load_auth_settings({"auth_enabled": "true"}, secret_directory=tmp_path)
    for key in ("oidc_issuer", "oidc_client_id", "oidc_client_secret", "oidc_redirect_uri", "oidc_owner_sub"):
        assert key in str(error.value)


@pytest.mark.usefixtures("clean_env")
def test_native_toml_bool_and_integer_are_accepted(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        f'source_directory = {json.dumps(str(source))}\nmodel_endpoint = ""\nauth_enabled = true\nsession_lifetime_minutes = 45\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("builtins.input", lambda *_: "")
    config = Configuration()
    config.handle_configuration(config_file)

    assert config.get_auth_values()["auth_enabled"] == "true"
    assert config.get_auth_values()["session_lifetime_minutes"] == "45"


@pytest.mark.usefixtures("clean_env")
def test_auth_keys_are_never_exposed_or_erased_by_config_saves(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    values = {
        "source_directory": str(source),
        "model_endpoint": "",
        **{key: f"value-for-{key}" for key in AUTH_TOML_KEYS if key != "auth_enabled"},
        "auth_enabled": "false",
    }
    config_file.write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *_: "")

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.get_auth_values() == {key: values[key] for key in AUTH_TOML_KEYS}
    assert not AUTH_TOML_KEYS.intersection(config.get_config_values())
    assert not AUTH_TOML_KEYS.intersection({field["key"] for field in config.field_specs()})

    config.apply_config_values({"recipe_server_name": "Renamed"})
    persisted = tomllib.loads(config_file.read_text(encoding="utf-8"))
    for key in AUTH_TOML_KEYS:
        assert persisted[key] == values[key]
