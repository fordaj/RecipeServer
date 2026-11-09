import json
import tomllib
from pathlib import Path

from recipeserver.config import (
    ALL_PURPOSE_MODEL_NAME_KEY,
    CONFIG_FILENAME,
    DEFAULT_FOOD_COLOR,
    DEFAULT_RECIPE_SERVER_NAME,
    DEFAULT_SERVER_PORT,
    FOOD_COLOR_KEY,
    IMAGE_ANALYSIS_MODEL_KEY,
    MODEL_ENDPOINT_KEY,
    MODEL_NAME_KEY,
    RECIPE_SERVER_NAME_KEY,
    SERVER_PORT_KEY,
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
        FOOD_COLOR_KEY: "#8d5542",
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
