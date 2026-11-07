from recipeserver.config import (
    ALL_PURPOSE_MODEL_NAME_KEY,
    DEFAULT_RECIPE_SERVER_NAME,
    IMAGE_ANALYSIS_MODEL_KEY,
    MODEL_ENDPOINT_KEY,
    MODEL_NAME_KEY,
    RECIPE_SERVER_NAME_KEY,
    Configuration,
)


def test_configuration_reads_and_persists_local_model_settings(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / "config.txt"
    config_file.write_text(str(source), encoding="UTF-8")

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

    saved_lines = config_file.read_text(encoding="UTF-8").splitlines()
    assert saved_lines[0] == str(source.resolve())
    assert f"{MODEL_ENDPOINT_KEY}=http://localhost:11434/v1" in saved_lines
    assert f"{ALL_PURPOSE_MODEL_NAME_KEY}=llama3.2" in saved_lines
    assert f"{IMAGE_ANALYSIS_MODEL_KEY}=llava3" in saved_lines

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
    config_file = tmp_path / "config.txt"
    config_file.write_text(
        "\n".join(
            [
                str(source),
                f"{MODEL_ENDPOINT_KEY}=http://127.0.0.1:1234/v1",
                f"{MODEL_NAME_KEY}=legacy-model",
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
    saved_lines = config_file.read_text(encoding="UTF-8").splitlines()
    assert f"{ALL_PURPOSE_MODEL_NAME_KEY}=legacy-model" in saved_lines
    assert not any(line.startswith(f"{MODEL_NAME_KEY}=") for line in saved_lines)


def test_configuration_skips_the_model_when_the_user_presses_enter(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / "config.txt"
    config_file.write_text(str(source), encoding="UTF-8")

    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    config = Configuration()
    config.handle_configuration(config_file)

    assert config.model_endpoint == ""
    assert config.all_purpose_model_name == ""
    assert config.image_analysis_model == ""
    assert not config.ai_configured
    assert config_file.read_text(encoding="UTF-8").splitlines() == [
        str(source.resolve()),
        f"{MODEL_ENDPOINT_KEY}=",
        f"{RECIPE_SERVER_NAME_KEY}={DEFAULT_RECIPE_SERVER_NAME}",
    ]

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
    config_file = tmp_path / "config.txt"
    config_file.write_text(
        "\n".join(
            [
                str(source),
                f"{MODEL_ENDPOINT_KEY}=",
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
    assert f"{RECIPE_SERVER_NAME_KEY}={DEFAULT_RECIPE_SERVER_NAME}" in config_file.read_text(
        encoding="UTF-8"
    ).splitlines()


def test_configuration_reads_and_persists_custom_recipe_server_name(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / "config.txt"
    config_file.write_text(
        "\n".join(
            [
                str(source),
                f"{MODEL_ENDPOINT_KEY}=",
                f"{RECIPE_SERVER_NAME_KEY}=The Andersons' Cookbook",
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
    assert f"{RECIPE_SERVER_NAME_KEY}=The Andersons' Cookbook" in config_file.read_text(
        encoding="UTF-8"
    ).splitlines()

    reloaded = Configuration()
    reloaded.handle_configuration(config_file)
    assert reloaded.recipe_server_name == "The Andersons' Cookbook"


def test_configuration_does_not_prompt_when_model_keys_already_exist(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config_file = tmp_path / "config.txt"
    config_file.write_text(
        "\n".join(
            [
                str(source),
                f"{MODEL_ENDPOINT_KEY}=http://127.0.0.1:1234/v1",
                f"{ALL_PURPOSE_MODEL_NAME_KEY}=local-model",
                f"{IMAGE_ANALYSIS_MODEL_KEY}=vision-model",
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
