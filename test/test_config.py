import json
import tomllib
from pathlib import Path

from recipeserver.config import (
    ALL_PURPOSE_MODEL_NAME_KEY,
    CONFIG_FILENAME,
    DEFAULT_FOOD_COLOR,
    DEFAULT_RECIPE_SERVER_NAME,
    DEFAULT_SERVER_BIND_ADDRESS,
    DEFAULT_SERVER_PORT,
    DEFAULT_KEEP_ALIVE_MINUTES,
    DEFAULT_TIMELINE_RETENTION,
    DEFAULT_TRANSCRIPTION_ENDPOINT,
    DEFAULT_TRANSCRIPTION_MODEL,
    ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY,
    IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY,
    FOOD_COLOR_KEY,
    DICTATION_ENABLED_KEY,
    DEFAULT_DICTATION_ENABLED,
    IMAGE_ANALYSIS_MODEL_KEY,
    MODEL_ENDPOINT_KEY,
    MODEL_NAME_KEY,
    TRANSCRIPTION_ENDPOINT_KEY,
    TRANSCRIPTION_KEEP_ALIVE_KEY,
    TRANSCRIPTION_MODEL_KEY,
    RECIPE_SERVER_NAME_KEY,
    SERVER_BIND_ADDRESS_KEY,
    SERVER_PORT_KEY,
    TIMELINE_RETENTION_KEY,
    Configuration,
)


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="UTF-8"))


def test_configuration_reads_and_persists_local_model_settings(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(f"source_directory = {json.dumps(str(source))}\n", encoding="UTF-8")

    answers = iter(["http://localhost:11434/v1", "llama3.2", "llava3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.source_directory == source.resolve()
    assert config.model_endpoint == "http://localhost:11434/v1"
    assert config.all_purpose_model_name == "llama3.2"
    assert config.model_name == "llama3.2"  # legacy alias
    assert config.image_analysis_model == "llava3"
    assert config.ai_configured
    assert "ONLY reply with the markdown file" in config.new_recipe_prompt
    assert "Transcribe all text" in config.new_recipe_from_image_prompt

    saved = _toml(config_file)
    assert saved["source_directory"] == str(source.resolve())
    assert saved[MODEL_ENDPOINT_KEY] == "http://localhost:11434/v1"
    assert saved[ALL_PURPOSE_MODEL_NAME_KEY] == "llama3.2"
    assert saved[IMAGE_ANALYSIS_MODEL_KEY] == "llava3"

    def unexpected_input(prompt=""):
        raise AssertionError("Saved model configuration should not prompt again")

    monkeypatch.setattr("builtins.input", unexpected_input)
    reloaded = Configuration()
    reloaded.handle_configuration(config_file)

    assert reloaded.model_endpoint == "http://localhost:11434/v1"
    assert reloaded.all_purpose_model_name == "llama3.2"
    assert reloaded.image_analysis_model == "llava3"


def test_configuration_reads_legacy_model_name_key(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        "\n".join(
            [
                f"source_directory = {json.dumps(str(source))}",
                f'{MODEL_ENDPOINT_KEY} = "http://127.0.0.1:1234/v1"',
                f'{MODEL_NAME_KEY} = "legacy-model"',
            ]
        ),
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.all_purpose_model_name == "legacy-model"
    saved = _toml(config_file)
    assert saved[ALL_PURPOSE_MODEL_NAME_KEY] == "legacy-model"
    assert MODEL_NAME_KEY not in saved


def test_configuration_skips_the_model_when_the_user_presses_enter(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(f"source_directory = {json.dumps(str(source))}\n", encoding="UTF-8")

    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.model_endpoint == ""
    assert config.all_purpose_model_name == ""
    assert config.image_analysis_model == ""
    assert not config.ai_configured
    assert _toml(config_file) == {
        "source_directory": str(source.resolve()),
        MODEL_ENDPOINT_KEY: "",
        ALL_PURPOSE_MODEL_NAME_KEY: "",
        IMAGE_ANALYSIS_MODEL_KEY: "",
        RECIPE_SERVER_NAME_KEY: DEFAULT_RECIPE_SERVER_NAME,
        SERVER_PORT_KEY: "8000",
        SERVER_BIND_ADDRESS_KEY: "0.0.0.0",
        FOOD_COLOR_KEY: "#8d5542",
        DICTATION_ENABLED_KEY: True,
        TRANSCRIPTION_ENDPOINT_KEY: "http://localhost:11434",
        TRANSCRIPTION_MODEL_KEY: "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0",
        TRANSCRIPTION_KEEP_ALIVE_KEY: "0",
        ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY: "0",
        IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY: "0",
        TIMELINE_RETENTION_KEY: "gfs",
    }

    def unexpected_input(prompt=""):
        raise AssertionError("A skipped model configuration should be remembered")

    monkeypatch.setattr("builtins.input", unexpected_input)
    reloaded = Configuration()
    reloaded.handle_configuration(config_file)

    assert reloaded.model_endpoint == ""
    assert not reloaded.ai_configured


def test_configuration_defaults_recipe_server_name(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        "\n".join(
            [
                f"source_directory = {json.dumps(str(source))}",
                f'{MODEL_ENDPOINT_KEY} = ""',
            ]
        ),
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.recipe_server_name == DEFAULT_RECIPE_SERVER_NAME
    assert config.recipe_server_name == "My Recipe Server"
    assert config.server_name == DEFAULT_RECIPE_SERVER_NAME
    assert _toml(config_file)[RECIPE_SERVER_NAME_KEY] == DEFAULT_RECIPE_SERVER_NAME


def test_configuration_reads_and_persists_custom_recipe_server_name(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        "\n".join(
            [
                f"source_directory = {json.dumps(str(source))}",
                f'{MODEL_ENDPOINT_KEY} = ""',
                f'{RECIPE_SERVER_NAME_KEY} = "The Andersons\' Cookbook"',
            ]
        ),
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.recipe_server_name == "The Andersons' Cookbook"
    assert config.server_name == "The Andersons' Cookbook"
    assert _toml(config_file)[RECIPE_SERVER_NAME_KEY] == "The Andersons' Cookbook"

    reloaded = Configuration()
    reloaded.handle_configuration(config_file)
    assert reloaded.recipe_server_name == "The Andersons' Cookbook"


def test_configuration_does_not_prompt_when_model_keys_already_exist(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        "\n".join(
            [
                f"source_directory = {json.dumps(str(source))}",
                f'{MODEL_ENDPOINT_KEY} = "http://127.0.0.1:1234/v1"',
                f'{ALL_PURPOSE_MODEL_NAME_KEY} = "local-model"',
                f'{IMAGE_ANALYSIS_MODEL_KEY} = "vision-model"',
            ]
        ),
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.model_endpoint == "http://127.0.0.1:1234/v1"
    assert config.all_purpose_model_name == "local-model"
    assert config.image_analysis_model == "vision-model"
    assert config.ai_configured


def test_configuration_migrates_legacy_config_txt(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    legacy_file = tmp_path / "config.txt"
    legacy_file.write_text(
        "\n".join(
            [
                str(source),
                f"{MODEL_ENDPOINT_KEY}=http://127.0.0.1:1234/v1",
                f"{MODEL_NAME_KEY}=legacy-model",
                f"{RECIPE_SERVER_NAME_KEY}=Legacy Name",
            ]
        ),
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Migrated model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)

    config = Configuration()
    config.handle_configuration(legacy_file)

    toml_file = tmp_path / CONFIG_FILENAME
    assert not legacy_file.exists()
    saved = _toml(toml_file)
    assert saved["source_directory"] == str(source.resolve())
    assert saved[MODEL_ENDPOINT_KEY] == "http://127.0.0.1:1234/v1"
    assert saved[ALL_PURPOSE_MODEL_NAME_KEY] == "legacy-model"
    assert saved[RECIPE_SERVER_NAME_KEY] == "Legacy Name"

    assert config._config_file == toml_file

    reloaded = Configuration()
    reloaded.handle_configuration(toml_file)
    assert reloaded.all_purpose_model_name == "legacy-model"
    assert reloaded.recipe_server_name == "Legacy Name"


def test_apply_config_values_validates_and_reports_changed_keys(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        f'source_directory = {json.dumps(str(source))}\n{MODEL_ENDPOINT_KEY} = ""\n',
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)
    config = Configuration()
    config.handle_configuration(config_file)

    changed = config.apply_config_values(
        {
            RECIPE_SERVER_NAME_KEY: "My New Kitchen",
            MODEL_ENDPOINT_KEY: "127.0.0.1:1234/v1",
            ALL_PURPOSE_MODEL_NAME_KEY: "local-model",
        }
    )

    assert changed == [
        RECIPE_SERVER_NAME_KEY,
        MODEL_ENDPOINT_KEY,
        ALL_PURPOSE_MODEL_NAME_KEY,
    ]
    assert config.recipe_server_name == "My New Kitchen"
    # Missing scheme is added, matching the startup prompt behaviour.
    assert config.model_endpoint == "http://127.0.0.1:1234/v1"

    saved = _toml(config_file)
    assert saved[RECIPE_SERVER_NAME_KEY] == "My New Kitchen"
    assert saved[MODEL_ENDPOINT_KEY] == "http://127.0.0.1:1234/v1"

    assert config.apply_config_values({RECIPE_SERVER_NAME_KEY: "My New Kitchen"}) == []


def test_apply_config_values_rejects_invalid_values(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        f'source_directory = {json.dumps(str(source))}\n{MODEL_ENDPOINT_KEY} = ""\n',
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)
    config = Configuration()
    config.handle_configuration(config_file)

    import pytest

    with pytest.raises(ValueError, match="must be an existing directory"):
        config.apply_config_values({"source_directory": str(tmp_path / "nope")})

    with pytest.raises(ValueError, match="must be a valid http"):
        config.apply_config_values({MODEL_ENDPOINT_KEY: "ftp://host/v1"})

    with pytest.raises(ValueError, match="at most"):
        config.apply_config_values({ALL_PURPOSE_MODEL_NAME_KEY: "x" * 300})

    with pytest.raises(ValueError, match="Unknown configuration key"):
        config.apply_config_values({"not_a_key": "value"})

    with pytest.raises(ValueError, match="must be text"):
        config.apply_config_values({MODEL_ENDPOINT_KEY: 123})

    # Nothing was applied on failure.
    assert config.source_directory == source.resolve()


def _load_config(tmp_path, monkeypatch, extra_lines=""):
    source = tmp_path / "recipes"
    source.mkdir(exist_ok=True)
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        f'source_directory = {json.dumps(str(source))}\n{MODEL_ENDPOINT_KEY} = ""\n{extra_lines}',
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)
    config = Configuration()
    config.handle_configuration(config_file)
    return config, config_file


def test_configuration_defaults_server_port_and_food_color(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    assert config.server_port == DEFAULT_SERVER_PORT == 8000
    assert config.food_color == DEFAULT_FOOD_COLOR == "#8d5542"
    assert config.get_config_values()[SERVER_PORT_KEY] == "8000"
    assert config.get_config_values()[FOOD_COLOR_KEY] == "#8d5542"


def test_configuration_reads_and_persists_custom_port_and_food_color(tmp_path, monkeypatch):
    config, config_file = _load_config(
        tmp_path,
        monkeypatch,
        f'{SERVER_PORT_KEY} = "9000"\n{FOOD_COLOR_KEY} = "#ABCDEF"\n',
    )

    assert config.server_port == 9000
    assert config.food_color == "#abcdef"

    saved = _toml(config_file)
    assert saved[SERVER_PORT_KEY] == "9000"
    assert saved[FOOD_COLOR_KEY] == "#abcdef"


def test_configuration_reads_bare_integer_port_from_toml(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch, f"{SERVER_PORT_KEY} = 9001\n")

    assert config.server_port == 9001


def test_configuration_falls_back_to_defaults_for_invalid_saved_values(tmp_path, monkeypatch):
    config, _ = _load_config(
        tmp_path,
        monkeypatch,
        f'{SERVER_PORT_KEY} = "not-a-port"\n{FOOD_COLOR_KEY} = "not-a-color"\n',
    )

    assert config.server_port == DEFAULT_SERVER_PORT
    assert config.food_color == DEFAULT_FOOD_COLOR


def test_apply_config_values_normalizes_port_and_food_color(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    changed = config.apply_config_values({SERVER_PORT_KEY: " 9000 ", FOOD_COLOR_KEY: "#ABC"})

    assert changed == [SERVER_PORT_KEY, FOOD_COLOR_KEY]
    assert config.server_port == 9000
    assert config.food_color == "#aabbcc"
    saved = _toml(config_file)
    assert saved[SERVER_PORT_KEY] == "9000"
    assert saved[FOOD_COLOR_KEY] == "#aabbcc"

    # Blank values fall back to the recommended defaults.
    changed = config.apply_config_values({SERVER_PORT_KEY: " ", FOOD_COLOR_KEY: ""})
    assert changed == [SERVER_PORT_KEY, FOOD_COLOR_KEY]
    assert config.server_port == DEFAULT_SERVER_PORT
    assert config.food_color == DEFAULT_FOOD_COLOR


def test_apply_config_values_rejects_invalid_port_and_food_color(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    import pytest

    for bad_port in ["0", "65536", "abc", "80.5", "-1"]:
        with pytest.raises(ValueError, match="Server port must be"):
            config.apply_config_values({SERVER_PORT_KEY: bad_port})

    for bad_color in ["red", "#12", "#12345", "123456", "#gggggg"]:
        with pytest.raises(ValueError, match="Food color must be"):
            config.apply_config_values({FOOD_COLOR_KEY: bad_color})

    assert config.server_port == DEFAULT_SERVER_PORT
    assert config.food_color == DEFAULT_FOOD_COLOR


def test_configuration_defaults_to_dictation_enabled(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    assert config.dictation_enabled is DEFAULT_DICTATION_ENABLED is True
    assert config.get_config_values()[DICTATION_ENABLED_KEY] == "true"
    assert _toml(config_file)[DICTATION_ENABLED_KEY] is True


def test_configuration_reads_and_persists_dictation_disabled(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch, f"{DICTATION_ENABLED_KEY} = false\n")

    assert config.dictation_enabled is False
    assert config.get_config_values()[DICTATION_ENABLED_KEY] == "false"

    saved = _toml(config_file)
    assert saved[DICTATION_ENABLED_KEY] is False


def test_configuration_reads_dictation_enabled_as_quoted_string(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch, f'{DICTATION_ENABLED_KEY} = "false"\n')

    assert config.dictation_enabled is False


def test_apply_config_values_round_trips_dictation(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    changed = config.apply_config_values({DICTATION_ENABLED_KEY: "false"})

    assert changed == [DICTATION_ENABLED_KEY]
    assert config.dictation_enabled is False
    assert _toml(config_file)[DICTATION_ENABLED_KEY] is False

    changed = config.apply_config_values({DICTATION_ENABLED_KEY: "true"})
    assert changed == [DICTATION_ENABLED_KEY]
    assert config.dictation_enabled is True


def test_apply_config_values_rejects_a_non_boolean_dictation_value(tmp_path, monkeypatch):
    import pytest

    config, _ = _load_config(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Dictation"):
        config.apply_config_values({DICTATION_ENABLED_KEY: "maybe"})

    # Nothing was applied on failure.
    assert config.dictation_enabled is True


def test_field_specs_expose_dictation_as_a_checkbox(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    specs = {field["key"]: field for field in config.field_specs()}

    assert specs[DICTATION_ENABLED_KEY]["input_type"] == "checkbox"
    assert specs[DICTATION_ENABLED_KEY]["label"] == "Dictation"


def test_configuration_defaults_to_gfs_timeline_retention(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    assert config.timeline_retention == DEFAULT_TIMELINE_RETENTION == "gfs"
    assert config.get_config_values()[TIMELINE_RETENTION_KEY] == "gfs"
    assert _toml(config_file)[TIMELINE_RETENTION_KEY] == "gfs"


def test_configuration_migrates_an_installation_without_the_key_to_gfs(tmp_path, monkeypatch):
    # An existing config file with no timeline_retention key migrates to GFS.
    config, config_file = _load_config(tmp_path, monkeypatch, 'food_color = "#123456"\n')

    assert config.timeline_retention == "gfs"
    assert _toml(config_file)[TIMELINE_RETENTION_KEY] == "gfs"


def test_configuration_reads_and_persists_unlimited_timeline_retention(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch, f'{TIMELINE_RETENTION_KEY} = "unlimited"\n')

    assert config.timeline_retention == "unlimited"

    saved = _toml(config_file)
    assert saved[TIMELINE_RETENTION_KEY] == "unlimited"


def test_apply_config_values_round_trips_timeline_retention(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    changed = config.apply_config_values({TIMELINE_RETENTION_KEY: "unlimited"})

    assert changed == [TIMELINE_RETENTION_KEY]
    assert config.timeline_retention == "unlimited"
    assert _toml(config_file)[TIMELINE_RETENTION_KEY] == "unlimited"


def test_apply_config_values_rejects_an_unknown_timeline_retention(tmp_path, monkeypatch):
    import pytest

    config, _ = _load_config(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Timeline retention"):
        config.apply_config_values({TIMELINE_RETENTION_KEY: "weekly"})

    assert config.timeline_retention == "gfs"


def test_unknown_timeline_retention_in_the_file_falls_back_to_gfs(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch, f'{TIMELINE_RETENTION_KEY} = "sometimes"\n')

    assert config.timeline_retention == "gfs"


def test_field_specs_expose_timeline_retention_as_a_select(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    specs = {field["key"]: field for field in config.field_specs()}

    spec = specs[TIMELINE_RETENTION_KEY]
    assert spec["input_type"] == "select"
    assert spec["label"] == "Timeline retention"
    assert spec["options"] == [
        {"value": "gfs", "label": "GFS (recommended)"},
        {"value": "unlimited", "label": "Unlimited"},
    ]
    assert "24 hours" in spec["help"]


def test_configuration_defaults_server_bind_address(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    assert config.server_bind_address == DEFAULT_SERVER_BIND_ADDRESS == "0.0.0.0"
    assert config.get_config_values()[SERVER_BIND_ADDRESS_KEY] == "0.0.0.0"


def test_configuration_reads_and_persists_bind_address(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch, f'{SERVER_BIND_ADDRESS_KEY} = "0.0.0.0"\n')

    assert config.server_bind_address == "0.0.0.0"

    saved = _toml(config_file)
    assert saved[SERVER_BIND_ADDRESS_KEY] == "0.0.0.0"


def test_configuration_reads_ipv6_bind_address(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch, f'{SERVER_BIND_ADDRESS_KEY} = "::"\n')

    assert config.server_bind_address == "::"


def test_configuration_falls_back_to_default_for_invalid_saved_bind_address(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch, f'{SERVER_BIND_ADDRESS_KEY} = "maestro.local"\n')

    assert config.server_bind_address == DEFAULT_SERVER_BIND_ADDRESS


def test_apply_config_values_normalizes_bind_address(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    changed = config.apply_config_values({SERVER_BIND_ADDRESS_KEY: " 127.0.0.1 "})

    assert changed == [SERVER_BIND_ADDRESS_KEY]
    assert config.server_bind_address == "127.0.0.1"
    saved = _toml(config_file)
    assert saved[SERVER_BIND_ADDRESS_KEY] == "127.0.0.1"

    # A blank value falls back to the documented default.
    changed = config.apply_config_values({SERVER_BIND_ADDRESS_KEY: " "})
    assert changed == [SERVER_BIND_ADDRESS_KEY]
    assert config.server_bind_address == DEFAULT_SERVER_BIND_ADDRESS


def test_apply_config_values_rejects_non_ip_bind_addresses(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    import pytest

    for bad_address in ["maestro.local", "localhost", "8000", "1.2.3.256", "0.0.0.0/0", "::g"]:
        with pytest.raises(ValueError, match="Bind address must be an IPv4 or IPv6 address"):
            config.apply_config_values({SERVER_BIND_ADDRESS_KEY: bad_address})

    assert config.server_bind_address == DEFAULT_SERVER_BIND_ADDRESS


def test_field_specs_expose_bind_address_as_a_text_field(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    specs = {field["key"]: field for field in config.field_specs()}

    assert specs[SERVER_BIND_ADDRESS_KEY]["input_type"] == "text"
    assert specs[SERVER_BIND_ADDRESS_KEY]["required"] is True


def test_configuration_defaults_to_ollama_transcription(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    assert config.transcription_endpoint == DEFAULT_TRANSCRIPTION_ENDPOINT == "http://localhost:11434"
    assert config.transcription_model == DEFAULT_TRANSCRIPTION_MODEL == "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0"
    assert config.transcription_keep_alive == DEFAULT_KEEP_ALIVE_MINUTES == "0"
    assert config.all_purpose_model_keep_alive == "0"
    assert config.image_analysis_model_keep_alive == "0"

    saved = _toml(config_file)
    assert saved[TRANSCRIPTION_ENDPOINT_KEY] == "http://localhost:11434"
    assert saved[TRANSCRIPTION_MODEL_KEY] == "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0"
    assert saved[TRANSCRIPTION_KEEP_ALIVE_KEY] == "0"
    assert saved[ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY] == "0"
    assert saved[IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY] == "0"


def test_configuration_reads_and_persists_transcription_settings(tmp_path, monkeypatch):
    extra = (
        f'{TRANSCRIPTION_ENDPOINT_KEY} = "http://127.0.0.1:11435"\n'
        f'{TRANSCRIPTION_MODEL_KEY} = "custom/audio-model:Q8_0"\n'
        f'{TRANSCRIPTION_KEEP_ALIVE_KEY} = "10"\n'
        f"{ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY} = -1\n"
        f'{IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY} = "30"\n'
    )
    config, config_file = _load_config(tmp_path, monkeypatch, extra)

    assert config.transcription_endpoint == "http://127.0.0.1:11435"
    assert config.transcription_model == "custom/audio-model:Q8_0"
    assert config.transcription_keep_alive == "10"
    # -1 as a bare TOML integer round-trips to the "-1" string.
    assert config.all_purpose_model_keep_alive == "-1"
    assert config.image_analysis_model_keep_alive == "30"

    saved = _toml(config_file)
    assert saved[TRANSCRIPTION_ENDPOINT_KEY] == "http://127.0.0.1:11435"
    assert saved[TRANSCRIPTION_MODEL_KEY] == "custom/audio-model:Q8_0"
    assert saved[TRANSCRIPTION_KEEP_ALIVE_KEY] == "10"
    assert saved[ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY] == "-1"
    assert saved[IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY] == "30"


def test_apply_config_values_round_trips_transcription_settings(tmp_path, monkeypatch):
    config, config_file = _load_config(tmp_path, monkeypatch)

    changed = config.apply_config_values(
        {
            TRANSCRIPTION_ENDPOINT_KEY: "127.0.0.1:11435",  # scheme is added
            TRANSCRIPTION_MODEL_KEY: "custom/audio-model:Q8_0",
            TRANSCRIPTION_KEEP_ALIVE_KEY: "-1",
            ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY: "60",
            IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY: "30",
        }
    )

    assert set(changed) == {
        TRANSCRIPTION_ENDPOINT_KEY,
        TRANSCRIPTION_MODEL_KEY,
        TRANSCRIPTION_KEEP_ALIVE_KEY,
        ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY,
        IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY,
    }
    assert config.transcription_endpoint == "http://127.0.0.1:11435"
    assert config.transcription_model == "custom/audio-model:Q8_0"
    assert config.transcription_keep_alive == "-1"
    assert config.all_purpose_model_keep_alive == "60"
    assert config.image_analysis_model_keep_alive == "30"

    saved = _toml(config_file)
    assert saved[TRANSCRIPTION_ENDPOINT_KEY] == "http://127.0.0.1:11435"
    assert saved[TRANSCRIPTION_MODEL_KEY] == "custom/audio-model:Q8_0"
    assert saved[TRANSCRIPTION_KEEP_ALIVE_KEY] == "-1"
    assert saved[ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY] == "60"
    assert saved[IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY] == "30"


def test_apply_config_values_rejects_invalid_transcription_values(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    import pytest

    with pytest.raises(ValueError, match="Transcription server"):
        config.apply_config_values({TRANSCRIPTION_ENDPOINT_KEY: "ftp://host"})
    with pytest.raises(ValueError, match="keep-alive"):
        config.apply_config_values({TRANSCRIPTION_KEEP_ALIVE_KEY: "forever"})

    assert config.transcription_endpoint == DEFAULT_TRANSCRIPTION_ENDPOINT
    assert config.transcription_keep_alive == DEFAULT_KEEP_ALIVE_MINUTES


def test_keep_alive_minutes_accepts_supported_spellings(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    for value in ["0", "-1", "1", "30", "525600"]:
        config.apply_config_values({TRANSCRIPTION_KEEP_ALIVE_KEY: value})
        assert config.transcription_keep_alive == value

    config.apply_config_values({TRANSCRIPTION_KEEP_ALIVE_KEY: "0"})
    for value in ["2.5", "-2", "abc", "10m", "1h"]:
        import pytest

        with pytest.raises(ValueError, match="keep-alive"):
            config.apply_config_values({TRANSCRIPTION_KEEP_ALIVE_KEY: value})
        assert config.transcription_keep_alive == "0"


def test_blank_transcription_values_fall_back_to_defaults(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    changed = config.apply_config_values(
        {
            TRANSCRIPTION_ENDPOINT_KEY: "",
            TRANSCRIPTION_MODEL_KEY: "",
            TRANSCRIPTION_KEEP_ALIVE_KEY: "",
        }
    )

    assert changed == []
    assert config.transcription_endpoint == DEFAULT_TRANSCRIPTION_ENDPOINT
    assert config.transcription_model == DEFAULT_TRANSCRIPTION_MODEL
    assert config.transcription_keep_alive == "0"


def test_keep_alive_rejects_non_integer_minutes(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    import pytest

    for value in ["infinity", "nan", "1e3", "++1", "0.0"]:
        with pytest.raises(ValueError, match="keep-alive"):
            config.apply_config_values({ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY: value})
        assert config.all_purpose_model_keep_alive == "0"

    # "-0" parses to 0 and is accepted as "unload immediately".
    config.apply_config_values({ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY: "-0"})
    assert config.all_purpose_model_keep_alive == "0"


def test_field_specs_expose_transcription_fields(tmp_path, monkeypatch):
    config, _ = _load_config(tmp_path, monkeypatch)

    specs = {field["key"]: field for field in config.field_specs()}

    assert specs[TRANSCRIPTION_ENDPOINT_KEY]["input_type"] == "url"
    assert specs[TRANSCRIPTION_MODEL_KEY]["input_type"] == "text"
    assert specs[TRANSCRIPTION_KEEP_ALIVE_KEY]["input_type"] == "number"
    assert specs[ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY]["input_type"] == "number"
    assert specs[IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY]["input_type"] == "number"
    assert specs[TRANSCRIPTION_ENDPOINT_KEY]["help"]
    assert specs[TRANSCRIPTION_MODEL_KEY]["help"]
    assert specs[TRANSCRIPTION_KEEP_ALIVE_KEY]["help"]
    assert specs[ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY]["min"] == -1
    assert specs[IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY]["min"] == -1
    assert specs[TRANSCRIPTION_KEEP_ALIVE_KEY]["min"] == -1
