import sys
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from platformdirs import user_data_path
from tkinter import Tk, filedialog
from typing import Optional
from urllib.parse import urlsplit

from ._logger import logger


MODEL_ENDPOINT_KEY = "model_endpoint"
MODEL_NAME_KEY = "model_name"  # Legacy key, read-only compatibility for the all-purpose model.
ALL_PURPOSE_MODEL_NAME_KEY = "all_purpose_model_name"
IMAGE_ANALYSIS_MODEL_KEY = "image_analysis_model"
RECIPE_SERVER_NAME_KEY = "recipe_server_name"
SERVER_NAME_KEY = "server_name"
SOURCE_DIRECTORY_KEY = "source_directory"
CONFIG_FILENAME = "recipe-server-cfg.toml"
LEGACY_CONFIG_FILENAME = "config.txt"
DEFAULT_RECIPE_SERVER_NAME = "My Recipe Server"
NEW_RECIPE_PROMPT_PATH = Path(__file__).resolve().parent / "NewRecipePrompt.md"
NEW_RECIPE_FROM_IMAGE_PROMPT_PATH = Path(__file__).resolve().parent / "NewRecipeFromImagePrompt.md"
_MAX_MODEL_NAME_LENGTH = 256
_LEGACY_SETTING_KEYS = {MODEL_NAME_KEY, SERVER_NAME_KEY}


def _known_toml_keys() -> set[str]:
    return {field.key for field in CONFIG_FIELDS} | _LEGACY_SETTING_KEYS


def _known_legacy_setting_keys() -> set[str]:
    return _known_toml_keys() - {SOURCE_DIRECTORY_KEY}


def _normalize_model_endpoint(value: str, *, strict: bool = True) -> str:
    endpoint = value.strip()
    if not endpoint:
        return ""
    if "://" not in endpoint:
        endpoint = f"http://{endpoint}"
    if not strict:
        return endpoint
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(
            "Local model endpoint must be a valid http:// or https:// endpoint "
            "(or left blank to disable AI recipe creation)."
        )
    return endpoint


@dataclass(frozen=True)
class ConfigField:
    """One editable configuration value.

    Add a field by appending an entry to ``CONFIG_FIELDS`` and applying the
    value in :meth:`Configuration.apply_config_values`. The server exposes
    these specs to the configuration editor UI, so no client code changes
    are needed for new fields.
    """

    key: str
    label: str
    help_text: str
    input_type: str = "text"  # "text", "url", or "path"
    placeholder: str = ""
    required: bool = False


CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(
        RECIPE_SERVER_NAME_KEY,
        "Server name",
        "Shown as the site title. Blank falls back to 'My Recipe Server'.",
        placeholder=DEFAULT_RECIPE_SERVER_NAME,
        required=True,
    ),
    ConfigField(
        SOURCE_DIRECTORY_KEY,
        "Recipes directory",
        "Must be an existing directory. The site is rebuilt from this folder on save.",
        input_type="path",
        placeholder="/path/to/recipes",
        required=True,
    ),
    ConfigField(
        MODEL_ENDPOINT_KEY,
        "Local model endpoint",
        "OpenAI-compatible endpoint, for example http://localhost:11434/v1. "
        "Leave blank to disable AI recipe creation. A scheme is added if omitted.",
        input_type="url",
        placeholder="http://localhost:11434/v1",
    ),
    ConfigField(
        ALL_PURPOSE_MODEL_NAME_KEY,
        "All-purpose model name",
        "Leave blank to auto-detect from the endpoint.",
        placeholder="llama3.2",
    ),
    ConfigField(
        IMAGE_ANALYSIS_MODEL_KEY,
        "Image analysis model name",
        "Used for From Image recipe creation. Leave blank to auto-detect from the endpoint.",
        placeholder="llava3",
    ),
)


def _validate_config_value(key: str, value: str) -> str:
    """Normalize and validate one configuration value.

    Returns the value to store. Raises ``ValueError`` with a user-facing
    message when the value is not acceptable.
    """
    label = next((field.label for field in CONFIG_FIELDS if field.key == key), key)

    if key == RECIPE_SERVER_NAME_KEY:
        return value.strip() or DEFAULT_RECIPE_SERVER_NAME

    if key == SOURCE_DIRECTORY_KEY:
        candidate = Path(value.strip()).expanduser()
        if not value.strip():
            raise ValueError(f"{label} is required and must be an existing directory.")
        if not candidate.is_dir():
            raise ValueError(f"{label} must be an existing directory.")
        return str(candidate.resolve())

    if key == MODEL_ENDPOINT_KEY:
        try:
            return _normalize_model_endpoint(value)
        except ValueError:
            raise ValueError(
                f"{label} must be a valid http:// or https:// endpoint "
                "(or left blank to disable AI recipe creation)."
            ) from None

    if key in (ALL_PURPOSE_MODEL_NAME_KEY, IMAGE_ANALYSIS_MODEL_KEY):
        name = value.strip()
        if len(name) > _MAX_MODEL_NAME_LENGTH:
            raise ValueError(
                f"{label} must be at most {_MAX_MODEL_NAME_LENGTH} characters."
            )
        return name

    raise ValueError(f"Unknown configuration key: {key}")


def _toml_string(value: str) -> str:
    """Render a string as a TOML basic string.

    JSON string escaping is a subset of TOML basic-string escaping, so the
    stdlib JSON encoder handles backslashes, quotes, and control characters.
    """
    return json.dumps(value, ensure_ascii=True)


class Configuration:
    def __init__(self):
        self.source_directory: Path = Path()
        self.model_endpoint: str = ""
        self._all_purpose_model_name: str = ""
        self.image_analysis_model: str = ""
        self._recipe_server_name: str = DEFAULT_RECIPE_SERVER_NAME
        self.new_recipe_prompt: str = ""
        self.new_recipe_from_image_prompt: str = ""
        self._config_file: Optional[Path] = None

    @property
    def all_purpose_model_name(self) -> str:
        return self._all_purpose_model_name

    @all_purpose_model_name.setter
    def all_purpose_model_name(self, value: str) -> None:
        self._all_purpose_model_name = value

    @property
    def model_name(self) -> str:
        """Legacy alias for the all-purpose model name."""
        return self._all_purpose_model_name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self._all_purpose_model_name = value

    @property
    def recipe_server_name(self) -> str:
        return self._recipe_server_name

    @recipe_server_name.setter
    def recipe_server_name(self, value: str) -> None:
        self._recipe_server_name = value.strip() or DEFAULT_RECIPE_SERVER_NAME

    @property
    def server_name(self) -> str:
        return self._recipe_server_name

    @server_name.setter
    def server_name(self, value: str) -> None:
        self._recipe_server_name = value.strip() or DEFAULT_RECIPE_SERVER_NAME

    @property
    def site_directory(self) -> Path:
        return user_data_path("recipe-server", appauthor=False) / "site"

    @property
    def ai_configured(self) -> bool:
        return bool(self.model_endpoint.strip() and self.new_recipe_prompt.strip())

    @property
    def image_ai_configured(self) -> bool:
        return bool(
            self.model_endpoint.strip() and self.new_recipe_from_image_prompt.strip()
        )

    def get_source_dir_from_user(self) -> Path:
        root = Tk()
        root.withdraw()

        try:
            selected = filedialog.askdirectory(
                title="Select a directory",
                initialdir=Path.home(),
                mustexist=True,
            )
        finally:
            root.destroy()

        if not selected:
            logger.info("User cancelled operation, exiting")
            sys.exit(0)

        return Path(selected).resolve()

    def get_config_contents_path_from_user_dir(self) -> Path:
        data_dir = user_data_path("recipe-server", appauthor=False)
        data_dir.mkdir(parents=True, exist_ok=True)

        return data_dir / CONFIG_FILENAME

    def _resolve_config_file(self, optional_config_path: Optional[Path] = None) -> Path:
        """Pick the config file to use, migrating the legacy file if needed.

        An explicitly passed path is always used as-is. Otherwise the TOML
        file is preferred; when it does not exist yet but a legacy
        ``config.txt`` does, that file is read and rewritten as TOML on save.
        """
        if optional_config_path:
            return optional_config_path

        data_dir = user_data_path("recipe-server", appauthor=False)
        data_dir.mkdir(parents=True, exist_ok=True)
        toml_file = data_dir / CONFIG_FILENAME
        if toml_file.exists():
            return toml_file

        legacy_file = data_dir / LEGACY_CONFIG_FILENAME
        if legacy_file.exists():
            logger.info(
                f"Migrating legacy configuration {legacy_file} to {toml_file}"
            )
            return legacy_file

        return toml_file

    @staticmethod
    def field_specs() -> list[dict[str, str | bool]]:
        """Serialisable field descriptions for the configuration editor UI."""
        return [
            {
                "key": field.key,
                "label": field.label,
                "help": field.help_text,
                "input_type": field.input_type,
                "placeholder": field.placeholder,
                "required": field.required,
            }
            for field in CONFIG_FIELDS
        ]

    def get_config_values(self) -> dict[str, str]:
        """Current values of every editable configuration field."""
        values: dict[str, str] = {}
        for field in CONFIG_FIELDS:
            if field.key == SOURCE_DIRECTORY_KEY:
                values[field.key] = str(self.source_directory)
            else:
                values[field.key] = str(getattr(self, field.key))
        return values

    def apply_config_values(self, values: dict) -> list[str]:
        """Validate and apply edited values, then persist them.

        Returns the list of keys whose stored value changed. Raises
        ``ValueError`` with a user-facing message on invalid input.
        """
        if not isinstance(values, dict):
            raise ValueError("Expected an object of configuration values.")

        known_keys = {field.key for field in CONFIG_FIELDS}
        normalized: dict[str, str] = {}
        for key, value in values.items():
            if key not in known_keys:
                raise ValueError(f"Unknown configuration key: {key}")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ValueError(f"Configuration value '{key}' must be text.")
            normalized[key] = _validate_config_value(key, value)

        from copy import deepcopy

        before = deepcopy(self.get_config_values())
        for key, value in normalized.items():
            if key == SOURCE_DIRECTORY_KEY:
                self.source_directory = Path(value)
            else:
                setattr(self, key, value)

        self._write_config(self._config_file or self._resolve_config_file())

        after = self.get_config_values()
        return [key for key in normalized if before.get(key) != after.get(key)]

    @classmethod
    def _parse_toml_config(cls, contents: str) -> tuple[str, dict[str, str]] | None:
        """Read the source directory and settings from TOML text.

        Returns ``None`` when the text is not valid TOML.
        """
        try:
            data = tomllib.loads(contents)
        except tomllib.TOMLDecodeError:
            logger.exception("Configuration file is not valid TOML")
            return None

        if not isinstance(data, dict):
            return None

        source_value = ""
        settings: dict[str, str] = {}
        known_keys = _known_toml_keys()
        for key, value in data.items():
            if not isinstance(value, str):
                logger.warning("Ignoring non-text configuration value for %r", key)
                continue
            if key == SOURCE_DIRECTORY_KEY:
                source_value = value.strip()
            elif key in known_keys:
                settings[key] = value.strip()

        return source_value, settings

    @classmethod
    def _parse_config(cls, contents: str) -> tuple[str, dict[str, str]]:
        """Read the source directory (first bare line) and optional model keys."""
        source_value = ""
        settings: dict[str, str] = {}
        known_keys = _known_legacy_setting_keys()

        for raw_line in contents.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            key, separator, value = line.partition("=")
            if separator and key.strip() in known_keys:
                settings[key.strip()] = value.strip()
            elif not source_value:
                source_value = line

        return source_value, settings

    @staticmethod
    def _prompt_user(prompt: str) -> str:
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def get_model_settings_from_user(self) -> None:
        """Optionally ask for an OpenAI-compatible local model endpoint."""
        print(
            "Optionally configure a local AI model so recipes can be created "
            "from text, a URL, or an image."
        )

        endpoint = self._prompt_user(
            "Local model endpoint (for example http://localhost:11434/v1). Press Enter to skip: "
        )
        if not endpoint:
            logger.info("No local model configured; AI recipe creation is disabled")
            self.model_endpoint = ""
            self.all_purpose_model_name = ""
            self.image_analysis_model = ""
            return

        self.model_endpoint = _normalize_model_endpoint(endpoint, strict=False)
        self.all_purpose_model_name = self._prompt_user(
            "All-purpose model name (press Enter to auto-detect from the endpoint): "
        )
        self.image_analysis_model = self._prompt_user(
            "Image analysis model name (press Enter to auto-detect from the endpoint): "
        )
        logger.info(
            "Configured local model endpoint: %s (all-purpose model: %s, image analysis model: %s)",
            self.model_endpoint,
            self.all_purpose_model_name or "auto-detect",
            self.image_analysis_model or "auto-detect",
        )

    @staticmethod
    def _load_prompt_file(path: Path) -> str:
        """Load a prompt file fresh so edits apply on the next run."""
        try:
            prompt = path.read_text(encoding="UTF-8").strip()
        except OSError:
            logger.exception(f"Failed to read new recipe prompt: {path}")
            prompt = ""

        logger.info(f"Loaded new recipe prompt from {path} ({len(prompt)} characters)")
        return prompt

    def load_new_recipe_prompt(self) -> str:
        """Load the prompt requirements fresh so edits apply on the next run."""
        prompt = self._load_prompt_file(NEW_RECIPE_PROMPT_PATH)
        self.new_recipe_prompt = prompt
        self.load_new_recipe_from_image_prompt()
        return prompt

    def load_new_recipe_from_image_prompt(self) -> str:
        """Load the image transcription prompt fresh so edits apply on the next run."""
        prompt = self._load_prompt_file(NEW_RECIPE_FROM_IMAGE_PROMPT_PATH)
        self.new_recipe_from_image_prompt = prompt
        return prompt

    def _write_config(self, config_file: Path) -> None:
        lines = [
            "# RecipeServer configuration.",
            "# Edit through the Configuration dialog in the app, or by hand here.",
            f"{SOURCE_DIRECTORY_KEY} = {_toml_string(str(self.source_directory))}",
            f"{MODEL_ENDPOINT_KEY} = {_toml_string(self.model_endpoint)}",
            f"{ALL_PURPOSE_MODEL_NAME_KEY} = {_toml_string(self.all_purpose_model_name)}",
            f"{IMAGE_ANALYSIS_MODEL_KEY} = {_toml_string(self.image_analysis_model)}",
            f"{RECIPE_SERVER_NAME_KEY} = {_toml_string(self.recipe_server_name)}",
        ]

        logger.debug(
            f"Saving configuration to {config_file} "
            f"(source={self.source_directory}, endpoint={self.model_endpoint or '(none)'}, "
            f"all-purpose model={self.all_purpose_model_name or '(auto)'}, "
            f"image analysis model={self.image_analysis_model or '(auto)'}, "
            f"server name={self.recipe_server_name!r})"
        )
        config_file.write_text("\n".join(lines) + "\n", encoding="UTF-8")

    def _read_and_parse_config(self, config_file: Path) -> tuple[str, dict[str, str]]:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        if not config_file.exists():
            logger.debug("Creating %s", config_file)
            config_file.touch()

        logger.debug("Reading %s", config_file)
        config_contents = config_file.read_text(encoding="UTF-8").strip()
        if config_file.suffix == ".toml":
            parsed = self._parse_toml_config(config_contents)
            config_source, settings = ("", {}) if parsed is None else parsed
        else:
            config_source, settings = self._parse_config(config_contents)

        logger.debug("Parsed configuration: source=%r, keys=%s", config_source, sorted(settings))
        return config_source, settings

    def _resolve_source_directory(self, config_source: str) -> Path:
        source_directory = Path(config_source).expanduser() if config_source else Path()
        if not config_source or not source_directory.is_dir():
            logger.warning("Recipe source directory is missing or invalid: %r", config_source)
            print("Recipes directory not found, please select from the file dialogue")
            source_directory = self.get_source_dir_from_user()
        resolved_source_directory = source_directory.resolve()
        logger.info("Using recipe source directory: %s", resolved_source_directory)
        return resolved_source_directory

    def _apply_loaded_settings(self, settings: dict[str, str]) -> None:
        server_name_value = settings.get(RECIPE_SERVER_NAME_KEY) or settings.get(SERVER_NAME_KEY, "")
        if server_name_value:
            self.recipe_server_name = server_name_value
        logger.debug("Configured recipe server name: %r", self.recipe_server_name)

        if MODEL_ENDPOINT_KEY in settings:
            self.model_endpoint = settings.get(MODEL_ENDPOINT_KEY, "")
            # The legacy singular model_name key remains readable but is
            # normalized to all_purpose_model_name on save.
            self.all_purpose_model_name = (
                settings.get(ALL_PURPOSE_MODEL_NAME_KEY) or settings.get(MODEL_NAME_KEY, "")
            )
            self.image_analysis_model = settings.get(IMAGE_ANALYSIS_MODEL_KEY, "")
            logger.info(
                "Using configured local model endpoint: %s (all-purpose model: %s, image analysis model: %s)",
                self.model_endpoint or "(none)",
                self.all_purpose_model_name or "auto-detect",
                self.image_analysis_model or "auto-detect",
            )
            return

        logger.debug("No %s key in configuration; prompting the user", MODEL_ENDPOINT_KEY)
        self.get_model_settings_from_user()

    def _persist_configuration(self, config_file: Path) -> Path:
        write_file = config_file
        if config_file.suffix != ".toml":
            # A legacy config.txt was read; persist as TOML from now on.
            write_file = config_file.with_name(CONFIG_FILENAME)
            self._write_config(write_file)
            try:
                config_file.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove legacy configuration %s", config_file)
            return write_file

        self._write_config(write_file)
        return write_file

    def handle_configuration(self, optional_config_path: Optional[Path] = None):
        config_file = self._resolve_config_file(optional_config_path)
        config_source, settings = self._read_and_parse_config(config_file)

        self.source_directory = self._resolve_source_directory(config_source)
        self._apply_loaded_settings(settings)

        self.load_new_recipe_prompt()
        logger.info(
            "AI recipe creation is %s (endpoint=%s, prompt=%s, image prompt=%s)",
            "enabled" if self.ai_configured else "disabled",
            "set" if self.model_endpoint else "missing",
            "set" if self.new_recipe_prompt else "missing",
            "set" if self.new_recipe_from_image_prompt else "missing",
        )

        self._config_file = self._persist_configuration(config_file)
