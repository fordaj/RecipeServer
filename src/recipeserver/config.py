import sys
import ipaddress
import json
from copy import deepcopy
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from platformdirs import user_data_path
from tkinter import Tk, filedialog
from urllib.parse import urlsplit

from ._logger import logger
from .auth_config import AUTH_TOML_KEYS
from .retention import DEFAULT_RETENTION_POLICY, RETENTION_POLICIES, RETENTION_POLICY_LABELS, normalize_retention_policy

MODEL_ENDPOINT_KEY = "model_endpoint"
MODEL_NAME_KEY = "model_name"  # Legacy key, read-only compatibility for the all-purpose model.
ALL_PURPOSE_MODEL_NAME_KEY = "all_purpose_model_name"
ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY = "all_purpose_model_keep_alive"
IMAGE_ANALYSIS_MODEL_KEY = "image_analysis_model"
IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY = "image_analysis_model_keep_alive"
TRANSCRIPTION_ENDPOINT_KEY = "transcription_endpoint"
TRANSCRIPTION_MODEL_KEY = "transcription_model"
TRANSCRIPTION_KEEP_ALIVE_KEY = "transcription_keep_alive"
RECIPE_SERVER_NAME_KEY = "recipe_server_name"
SERVER_NAME_KEY = "server_name"
SERVER_PORT_KEY = "server_port"
SERVER_BIND_ADDRESS_KEY = "server_bind_address"
FOOD_COLOR_KEY = "food_color"
DICTATION_ENABLED_KEY = "dictation_enabled"
TIMELINE_RETENTION_KEY = "timeline_retention"
SOURCE_DIRECTORY_KEY = "source_directory"
CONFIG_FILENAME = "recipe-server-cfg.toml"
LEGACY_CONFIG_FILENAME = "config.txt"
DEFAULT_RECIPE_SERVER_NAME = "My Recipe Server"
DEFAULT_SERVER_PORT = 8000
# Accepts connections on every IPv4 interface, matching the documented
# default in SERVER_BIND_ADDRESS. Restrict with server_bind_address = "127.0.0.1".
DEFAULT_SERVER_BIND_ADDRESS = "0.0.0.0"
# Dictation records a clip in the browser and transcribes it with the
# Qwen3-ASR model on an externally managed Ollama server. It is on by
# default; the switch only decides whether the app offers the feature at
# all. RecipeServer never downloads, installs, launches, or manages the
# Ollama server or its models.
DEFAULT_DICTATION_ENABLED = True
DEFAULT_TRANSCRIPTION_ENDPOINT = "http://localhost:11434"
DEFAULT_TRANSCRIPTION_MODEL = "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0"
# Keep-alive for every supported model, in minutes before unload:
# 0 = unload immediately (the default), -1 = never unload, any other
# positive whole number of minutes. Stored as text in the TOML file,
# mirroring server_port.
DEFAULT_KEEP_ALIVE_MINUTES = "0"
# Timeline revision retention: how historical snapshots are pruned. GFS is
# the default for new and existing installations; "unlimited" keeps every
# revision, preserving the historical behavior.
DEFAULT_TIMELINE_RETENTION = DEFAULT_RETENTION_POLICY
MAX_PORT = 65535
# Matches the --food-color default in assets/definitions.css.
DEFAULT_FOOD_COLOR = "#8d5542"
NEW_RECIPE_PROMPT_PATH = Path(__file__).resolve().parent / "NewRecipePrompt.md"
NEW_RECIPE_FROM_IMAGE_PROMPT_PATH = Path(__file__).resolve().parent / "NewRecipeFromImagePrompt.md"
_MAX_MODEL_NAME_LENGTH = 256
_LEGACY_SETTING_KEYS = {MODEL_NAME_KEY, SERVER_NAME_KEY}
_LEGACY_KEY_MAPPING = {MODEL_NAME_KEY: ALL_PURPOSE_MODEL_NAME_KEY, SERVER_NAME_KEY: RECIPE_SERVER_NAME_KEY}


def _known_toml_keys() -> set[str]:
    return {field.key for field in CONFIG_FIELDS} | _LEGACY_SETTING_KEYS


def _known_legacy_setting_keys() -> set[str]:
    return _known_toml_keys() - {SOURCE_DIRECTORY_KEY}


def _normalize_model_endpoint(value: str) -> str:
    endpoint = value.strip()
    if not endpoint:
        return ""
    if "://" not in endpoint:
        endpoint = f"http://{endpoint}"
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("Local model endpoint must be a valid http:// or https:// endpoint (or left blank to disable AI recipe creation).")
    return endpoint


_HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _normalize_food_color(value: str) -> str:
    """Normalize a hex color to lowercase ``#rrggbb`` form."""
    color = value.strip()
    if not _HEX_COLOR_PATTERN.match(color):
        raise ValueError("Food color must be a hex string such as #8d5542 (or #842).")
    digits = color[1:].lower()
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return f"#{digits}"


def _normalize_server_port(value: str) -> int:
    """Parse and range-check a server port."""
    text = value.strip()
    if not text.isdigit():
        raise ValueError("Server port must be a whole number between 1 and 65535.")
    port = int(text)
    if not 1 <= port <= MAX_PORT:
        raise ValueError("Server port must be between 1 and 65535.")
    return port


# Field validators. Each one normalizes one raw string from the editor UI or
# the TOML file and returns the value to store, or raises ``ValueError`` with
# a user-facing message. ``label`` is the field's display name, used in the
# message. A blank value falls back to the field's documented default where
# one exists.


def _validate_recipe_server_name(value: str, _label: str) -> str:
    return value.strip() or DEFAULT_RECIPE_SERVER_NAME


def _validate_source_directory(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{label} is required and must be an existing directory.")
    candidate = Path(text).expanduser()
    if not candidate.is_dir():
        raise ValueError(f"{label} must be an existing directory.")
    return str(candidate.resolve())


def _validate_model_endpoint(value: str, label: str) -> str:
    try:
        return _normalize_model_endpoint(value)
    except ValueError:
        raise ValueError(f"{label} must be a valid http:// or https:// endpoint (or left blank to disable AI recipe creation).") from None


def _validate_model_name(value: str, label: str) -> str:
    name = value.strip()
    if len(name) > _MAX_MODEL_NAME_LENGTH:
        raise ValueError(f"{label} must be at most {_MAX_MODEL_NAME_LENGTH} characters.")
    return name


def _validate_transcription_endpoint(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        return DEFAULT_TRANSCRIPTION_ENDPOINT
    try:
        return _normalize_model_endpoint(text)
    except ValueError:
        raise ValueError(f"{label} must be a valid http:// or https:// endpoint.") from None


def _validate_transcription_model(value: str, label: str) -> str:
    name = value.strip()
    if not name:
        return DEFAULT_TRANSCRIPTION_MODEL
    if len(name) > _MAX_MODEL_NAME_LENGTH:
        raise ValueError(f"{label} must be at most {_MAX_MODEL_NAME_LENGTH} characters.")
    return name


# Keep-alive for every supported model: an integer number of minutes
# ("0" — unload immediately, the default; "-1" — never unload; "<N>" —
# minutes). Plain seconds are sent to Ollama, so the value is scaled on use.
_KEEP_ALIVE_MINUTES_PATTERN = re.compile(r"^-?\d+$")


def _validate_keep_alive_minutes(value: str, label: str) -> str:
    text = str(value).strip()
    if not text:
        return DEFAULT_KEEP_ALIVE_MINUTES
    if not _KEEP_ALIVE_MINUTES_PATTERN.match(text):
        raise ValueError(f"{label} must be a whole number of minutes: -1 to never unload, 0 to unload immediately, or a positive number of minutes.")
    minutes = int(text, 10)
    if minutes < -1:
        raise ValueError(f"{label} must be -1 (never unload), 0 (unload immediately), or a positive number of minutes.")
    return str(minutes)


def _validate_server_port(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        return str(DEFAULT_SERVER_PORT)
    try:
        return str(_normalize_server_port(text))
    except ValueError:
        raise ValueError(f"{label} must be a whole number between 1 and 65535.") from None


def _validate_server_bind_address(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        return DEFAULT_SERVER_BIND_ADDRESS
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        raise ValueError(f"{label} must be an IPv4 or IPv6 address such as 127.0.0.1 or 0.0.0.0.") from None
    return str(address)


def _validate_food_color(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        return DEFAULT_FOOD_COLOR
    try:
        return _normalize_food_color(text)
    except ValueError:
        raise ValueError(f"{label} must be a hex string such as #8d5542.") from None


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _normalize_dictation_enabled(value) -> bool:
    """Normalize a dictation_enabled value to a boolean."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    if not text:
        return DEFAULT_DICTATION_ENABLED
    raise ValueError(f"Dictation must be true or false, not {value!r}.")


def _validate_dictation_enabled(value: str, label: str) -> str:
    try:
        return "true" if _normalize_dictation_enabled(value) else "false"
    except ValueError:
        raise ValueError(f"{label} must be true or false.") from None


def _validate_timeline_retention(value: str, label: str) -> str:
    text = value.strip().lower()
    if not text:
        return DEFAULT_TIMELINE_RETENTION
    if text in RETENTION_POLICIES:
        return text
    raise ValueError(f"{label} must be one of: {', '.join(RETENTION_POLICIES)}.")


@dataclass(frozen=True)
class ConfigField:
    """One editable configuration value.

    Add a field by appending one entry to ``CONFIG_FIELDS``. The validator
    normalizes and checks the value; the editor field specs, value loading,
    and TOML serialization are all derived from the same list, so no other
    sites need to know about the new field. The server exposes these specs
    to the configuration editor UI, so no client code changes are needed for
    new fields.
    """

    key: str
    label: str
    help_text: str
    validate: Callable[[str, str], str]
    input_type: str = "text"  # "text", "url", "path", "number", "checkbox", or "select"
    placeholder: str = ""
    required: bool = False
    options: tuple[tuple[str, str], ...] = ()  # (value, label) pairs for input_type="select"
    min_value: int | None = None  # lower bound for input_type="number"
    max_value: int | None = None  # upper bound for input_type="number"; None means unbounded


CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(
        RECIPE_SERVER_NAME_KEY,
        "Server name",
        "Shown as the site title. Blank falls back to 'My Recipe Server'.",
        _validate_recipe_server_name,
        placeholder=DEFAULT_RECIPE_SERVER_NAME,
        required=True,
    ),
    ConfigField(
        SOURCE_DIRECTORY_KEY,
        "Recipes directory",
        "Must be an existing directory. The site is rebuilt from this folder on save.",
        _validate_source_directory,
        input_type="path",
        placeholder="/path/to/recipes",
        required=True,
    ),
    ConfigField(
        MODEL_ENDPOINT_KEY,
        "Local model endpoint",
        "Ollama server endpoint, for example http://127.0.0.1:11434. Leave blank to disable AI recipe creation. A scheme is added if omitted.",
        _validate_model_endpoint,
        input_type="url",
        placeholder="http://127.0.0.1:11434",
    ),
    ConfigField(
        ALL_PURPOSE_MODEL_NAME_KEY,
        "All-purpose model name",
        "Leave blank to auto-detect from the endpoint.",
        _validate_model_name,
        placeholder="llama3.2",
    ),
    ConfigField(
        ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY,
        "All-purpose model keep-alive",
        "Minutes before the model unloads after each request: -1 never unloads, 0 unloads immediately (default), or a positive whole number of minutes."
        " Kept disabled while the model cannot be verified on the configured endpoint.",
        _validate_keep_alive_minutes,
        input_type="number",
        placeholder="0",
        min_value=-1,
    ),
    ConfigField(
        IMAGE_ANALYSIS_MODEL_KEY,
        "Image analysis model name",
        "Used for From Images recipe creation. Leave blank to auto-detect from the endpoint.",
        _validate_model_name,
        placeholder="llava3",
    ),
    ConfigField(
        IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY,
        "Image analysis model keep-alive",
        "Minutes before the model unloads after each request: -1 never unloads, 0 unloads immediately (default), or a positive whole number of minutes."
        " Kept disabled while the model cannot be verified on the configured endpoint.",
        _validate_keep_alive_minutes,
        input_type="number",
        placeholder="0",
        min_value=-1,
    ),
    ConfigField(
        SERVER_PORT_KEY,
        "Server port",
        "Port the local server listens on. Takes effect the next time the app starts.",
        _validate_server_port,
        input_type="number",
        placeholder=str(DEFAULT_SERVER_PORT),
        required=True,
        min_value=1,
        max_value=MAX_PORT,
    ),
    ConfigField(
        SERVER_BIND_ADDRESS_KEY,
        "Bind address",
        "Address the local server listens on. The default, 0.0.0.0, accepts"
        " connections on every IPv4 interface, so the site is reachable from"
        " the local network as http://<hostname>.local:8000. The site has no"
        " authentication; anyone who can reach this machine can load and edit"
        " recipes over plain HTTP. Set 127.0.0.1 to accept connections from"
        " this machine only (recommended when using a reverse proxy for"
        " remote access), or :: for every IPv6 interface. Takes effect the"
        " next time the app starts.",
        _validate_server_bind_address,
        placeholder=DEFAULT_SERVER_BIND_ADDRESS,
        required=True,
    ),
    ConfigField(
        FOOD_COLOR_KEY,
        "Food color",
        "Accent color used across the site, as a hex string such as #8d5542."
        " Blank falls back to the recommended default. Recipes with a photo"
        " still derive their own accent from that photo.",
        _validate_food_color,
        placeholder=DEFAULT_FOOD_COLOR,
    ),
    ConfigField(
        DICTATION_ENABLED_KEY,
        "Dictation",
        "Enable the dictation button in the search field. A short clip is"
        " recorded in the browser and transcribed on the Ollama server configured"
        " below, with the Qwen3-ASR model. Disable to hide the button and turn"
        " the transcription API off.",
        _validate_dictation_enabled,
        input_type="checkbox",
    ),
    ConfigField(
        TRANSCRIPTION_ENDPOINT_KEY,
        "Transcription server",
        "Ollama server used to transcribe dictation, for example http://localhost:11434."
        " The server and its models are managed independently of RecipeServer;"
        " leave blank to use the default. The recommended model is pulled with"
        " 'ollama pull hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0'.",
        _validate_transcription_endpoint,
        input_type="url",
        placeholder=DEFAULT_TRANSCRIPTION_ENDPOINT,
    ),
    ConfigField(
        TRANSCRIPTION_MODEL_KEY,
        "Transcription model",
        "The Ollama model used for dictation. Defaults to the Qwen3-ASR model;" " it must support audio input. Leave blank to use the default.",
        _validate_transcription_model,
        placeholder=DEFAULT_TRANSCRIPTION_MODEL,
    ),
    ConfigField(
        TRANSCRIPTION_KEEP_ALIVE_KEY,
        "Transcription keep-alive",
        "Minutes before the model unloads after each dictation: -1 never unloads, 0 unloads immediately (default), or a positive whole number of minutes."
        " Kept disabled while the model cannot be verified on the configured endpoint.",
        _validate_keep_alive_minutes,
        input_type="number",
        placeholder="0",
        min_value=-1,
    ),
    ConfigField(
        TIMELINE_RETENTION_KEY,
        "Timeline retention",
        "How historical revisions are kept. 'GFS' (default) keeps every revision"
        " from the last 24 hours, one per hour for the last 7 days, one per day"
        " for the last 30 days, one per week for the last 12 months, and one per"
        " month beyond that, removing older redundant revisions automatically in"
        " the background. 'Unlimited' keeps every revision forever. Switching"
        " policies never resets or migrates history.",
        _validate_timeline_retention,
        input_type="select",
        options=tuple((policy, RETENTION_POLICY_LABELS[policy]) for policy in RETENTION_POLICIES),
    ),
)

_CONFIG_FIELDS_BY_KEY = {field.key: field for field in CONFIG_FIELDS}


def _validate_config_value(key: str, value: str) -> str:
    """Normalize and validate one configuration value.

    Returns the value to store. Raises ``ValueError`` with a user-facing
    message when the value is not acceptable.
    """
    field = _CONFIG_FIELDS_BY_KEY.get(key)
    if field is None:
        raise ValueError(f"Unknown configuration key: {key}")
    return field.validate(value, field.label)


def _toml_string(value: str) -> str:
    """Render a string as a TOML basic string.

    JSON string escaping is a subset of TOML basic-string escaping, so the
    stdlib JSON encoder handles backslashes, quotes, and control characters.
    """
    return json.dumps(value, ensure_ascii=True)


class Configuration:
    """Mutable access to the recipe-server configuration.

    Setter policy: assignment never raises. Text values are stripped; a
    blank value falls back to the field's documented default. Typed fields
    (``server_port``, ``server_bind_address``, ``food_color``) validate their
    input; an invalid non-blank value falls back to the field's default
    with a logged warning. Model-name setters strip whitespace and otherwise
    accept any text (blank means auto-detect), matching the validators used
    for user-supplied edits.
    """

    def __init__(self):
        self._source_directory: Path = Path()
        self.model_endpoint: str = ""
        self._all_purpose_model_name: str = ""
        self._image_analysis_model: str = ""
        self._recipe_server_name: str = DEFAULT_RECIPE_SERVER_NAME
        self._server_port: int = DEFAULT_SERVER_PORT
        self._server_bind_address: str = DEFAULT_SERVER_BIND_ADDRESS
        self._food_color: str = DEFAULT_FOOD_COLOR
        self._dictation_enabled: bool = DEFAULT_DICTATION_ENABLED
        self._transcription_endpoint: str = DEFAULT_TRANSCRIPTION_ENDPOINT
        self._transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL
        self._all_purpose_model_keep_alive: str = DEFAULT_KEEP_ALIVE_MINUTES
        self._image_analysis_model_keep_alive: str = DEFAULT_KEEP_ALIVE_MINUTES
        self._transcription_keep_alive: str = DEFAULT_KEEP_ALIVE_MINUTES
        self._timeline_retention: str = DEFAULT_TIMELINE_RETENTION
        self.new_recipe_prompt: str = ""
        self.new_recipe_from_image_prompt: str = ""
        self._config_file: Path | None = None
        # Raw auth keys from the TOML file. They are never part of CONFIG_FIELDS,
        # so they cannot be edited through /api/config or returned to the browser.
        self._auth_values: dict[str, str] = {}

    @property
    def source_directory(self) -> Path:
        return self._source_directory

    @source_directory.setter
    def source_directory(self, value) -> None:
        self._source_directory = value if isinstance(value, Path) else Path(value)

    @property
    def all_purpose_model_name(self) -> str:
        return self._all_purpose_model_name

    @all_purpose_model_name.setter
    def all_purpose_model_name(self, value: str) -> None:
        self._all_purpose_model_name = str(value).strip()

    @property
    def model_name(self) -> str:
        """Legacy alias for the all-purpose model name."""
        return self._all_purpose_model_name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self._all_purpose_model_name = str(value).strip()

    @property
    def image_analysis_model(self) -> str:
        return self._image_analysis_model

    @image_analysis_model.setter
    def image_analysis_model(self, value: str) -> None:
        self._image_analysis_model = str(value).strip()

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
    def server_port(self) -> int:
        return self._server_port

    @server_port.setter
    def server_port(self, value) -> None:
        try:
            self._server_port = _normalize_server_port(str(value))
        except ValueError:
            logger.warning(f"Ignoring invalid {SERVER_PORT_KEY} value {value!r}; using default port {DEFAULT_SERVER_PORT}")
            self._server_port = DEFAULT_SERVER_PORT

    @property
    def server_bind_address(self) -> str:
        return self._server_bind_address

    @server_bind_address.setter
    def server_bind_address(self, value) -> None:
        try:
            self._server_bind_address = _validate_server_bind_address(str(value), "Bind address")
        except ValueError:
            logger.warning(f"Ignoring invalid {SERVER_BIND_ADDRESS_KEY} value {value!r}; using default address {DEFAULT_SERVER_BIND_ADDRESS}")
            self._server_bind_address = DEFAULT_SERVER_BIND_ADDRESS

    @property
    def food_color(self) -> str:
        return self._food_color

    @food_color.setter
    def food_color(self, value: str) -> None:
        try:
            self._food_color = _normalize_food_color(str(value))
        except ValueError:
            logger.warning(f"Ignoring invalid {FOOD_COLOR_KEY} value {value!r}; using default food color {DEFAULT_FOOD_COLOR}")
            self._food_color = DEFAULT_FOOD_COLOR

    @property
    def dictation_enabled(self) -> bool:
        return self._dictation_enabled

    @dictation_enabled.setter
    def dictation_enabled(self, value) -> None:
        try:
            self._dictation_enabled = _normalize_dictation_enabled(value)
        except ValueError:
            logger.warning(f"Ignoring invalid {DICTATION_ENABLED_KEY} value {value!r}; using default {DEFAULT_DICTATION_ENABLED}")
            self._dictation_enabled = DEFAULT_DICTATION_ENABLED

    @property
    def transcription_endpoint(self) -> str:
        return self._transcription_endpoint

    @transcription_endpoint.setter
    def transcription_endpoint(self, value) -> None:
        try:
            self._transcription_endpoint = _validate_transcription_endpoint(str(value), "Transcription server")
        except ValueError:
            logger.warning(f"Ignoring invalid {TRANSCRIPTION_ENDPOINT_KEY} value {value!r}; using default {DEFAULT_TRANSCRIPTION_ENDPOINT}")
            self._transcription_endpoint = DEFAULT_TRANSCRIPTION_ENDPOINT

    @property
    def transcription_model(self) -> str:
        return self._transcription_model

    @transcription_model.setter
    def transcription_model(self, value) -> None:
        try:
            self._transcription_model = _validate_transcription_model(str(value), "Transcription model")
        except ValueError:
            logger.warning(f"Ignoring invalid {TRANSCRIPTION_MODEL_KEY} value {value!r}; using default {DEFAULT_TRANSCRIPTION_MODEL}")
            self._transcription_model = DEFAULT_TRANSCRIPTION_MODEL

    @property
    def all_purpose_model_keep_alive(self) -> str:
        return self._all_purpose_model_keep_alive

    @all_purpose_model_keep_alive.setter
    def all_purpose_model_keep_alive(self, value) -> None:
        try:
            self._all_purpose_model_keep_alive = _validate_keep_alive_minutes(str(value), "All-purpose model keep-alive")
        except ValueError:
            logger.warning(f"Ignoring invalid {ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY} value {value!r}; using default {DEFAULT_KEEP_ALIVE_MINUTES}")
            self._all_purpose_model_keep_alive = DEFAULT_KEEP_ALIVE_MINUTES

    @property
    def image_analysis_model_keep_alive(self) -> str:
        return self._image_analysis_model_keep_alive

    @image_analysis_model_keep_alive.setter
    def image_analysis_model_keep_alive(self, value) -> None:
        try:
            self._image_analysis_model_keep_alive = _validate_keep_alive_minutes(str(value), "Image analysis model keep-alive")
        except ValueError:
            logger.warning(f"Ignoring invalid {IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY} value {value!r}; using default {DEFAULT_KEEP_ALIVE_MINUTES}")
            self._image_analysis_model_keep_alive = DEFAULT_KEEP_ALIVE_MINUTES

    @property
    def transcription_keep_alive(self) -> str:
        return self._transcription_keep_alive

    @transcription_keep_alive.setter
    def transcription_keep_alive(self, value) -> None:
        try:
            self._transcription_keep_alive = _validate_keep_alive_minutes(str(value), "Transcription keep-alive")
        except ValueError:
            logger.warning(f"Ignoring invalid {TRANSCRIPTION_KEEP_ALIVE_KEY} value {value!r}; using default {DEFAULT_KEEP_ALIVE_MINUTES}")
            self._transcription_keep_alive = DEFAULT_KEEP_ALIVE_MINUTES

    @property
    def timeline_retention(self) -> str:
        return self._timeline_retention

    @timeline_retention.setter
    def timeline_retention(self, value) -> None:
        self._timeline_retention = normalize_retention_policy(value)

    @property
    def site_directory(self) -> Path:
        return user_data_path("recipe-server", appauthor=False) / "site"

    @property
    def ai_configured(self) -> bool:
        return bool(self.model_endpoint.strip() and self.new_recipe_prompt.strip())

    @property
    def image_ai_configured(self) -> bool:
        return bool(self.model_endpoint.strip() and self.new_recipe_from_image_prompt.strip())

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

    def _resolve_config_file(self, optional_config_path: Path | None = None) -> Path:
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
            logger.info(f"Migrating legacy configuration {legacy_file} to {toml_file}")
            return legacy_file

        return toml_file

    @staticmethod
    def field_specs() -> list[dict[str, str | bool | int]]:
        """Serialisable field descriptions for the configuration editor UI."""
        return [
            {
                "key": field.key,
                "label": field.label,
                "help": field.help_text,
                "input_type": field.input_type,
                "placeholder": field.placeholder,
                "required": field.required,
                **({"options": [{"value": value, "label": label} for value, label in field.options]} if field.options else {}),
                **({"min": field.min_value} if field.min_value is not None else {}),
                **({"max": field.max_value} if field.max_value is not None else {}),
            }
            for field in CONFIG_FIELDS
        ]

    def get_auth_values(self) -> dict[str, str]:
        """Raw auth settings read from the TOML file (never from the web API).

        The returned mapping is a copy: callers cannot mutate the configuration
        through it, and none of these keys appear in ``get_config_values()`` or
        ``field_specs()``, which are the only values ``GET /api/config`` serves.
        """
        return dict(self._auth_values)

    def get_config_values(self) -> dict[str, str]:
        """Current values of every editable configuration field."""
        values: dict[str, str] = {}
        for field in CONFIG_FIELDS:
            value = getattr(self, field.key)
            # TOML booleans round-trip as lowercase strings; everything else
            # stringifies.
            if isinstance(value, bool):
                values[field.key] = "true" if value else "false"
            else:
                values[field.key] = str(value)
        return values

    def apply_config_values(self, values: dict) -> list[str]:
        """Validate and apply edited values, then persist them.

        Returns the list of keys whose stored value changed. Raises
        ``ValueError`` with a user-facing message on invalid input.
        """
        if not isinstance(values, dict):
            raise ValueError("Expected an object of configuration values.")

        normalized: dict[str, str] = {}
        for key, value in values.items():
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ValueError(f"Configuration value '{key}' must be text.")
            normalized[key] = _validate_config_value(key, value)

        before = deepcopy(self.get_config_values())
        for key, value in normalized.items():
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
        keep_alive_keys = {ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY, IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY, TRANSCRIPTION_KEEP_ALIVE_KEY}
        for key, value in data.items():
            # Auth keys are intentionally outside CONFIG_FIELDS: keep them in
            # their own mapping so they survive config saves and never leak to
            # the configuration editor or the generated site.
            if key in AUTH_TOML_KEYS:
                # Hand-edited files naturally use a real TOML boolean for
                # auth_enabled and a bare integer for the lifetime.
                if key == "auth_enabled" and isinstance(value, bool):
                    settings[key] = "true" if value else "false"
                elif key == "session_lifetime_minutes" and isinstance(value, int) and not isinstance(value, bool):
                    settings[key] = str(value)
                elif isinstance(value, str):
                    settings[key] = value.strip()
                else:
                    logger.warning(f"Ignoring invalid authentication configuration value for {key!r}")
                continue
            # server_port is written as a TOML string but hand-edited files
            # often contain a bare integer; accept both and normalize to text.
            if key == SERVER_PORT_KEY and isinstance(value, int) and not isinstance(value, bool):
                settings[key] = str(value)
                continue
            # The keep-alive minutes keys are written as TOML strings; accept
            # bare integers as well.
            if key in keep_alive_keys and isinstance(value, int) and not isinstance(value, bool):
                settings[key] = str(value)
                continue
            # dictation_enabled is written as a TOML boolean; accept both.
            if key == DICTATION_ENABLED_KEY and isinstance(value, bool):
                settings[key] = "true" if value else "false"
                continue
            if not isinstance(value, str):
                logger.warning(f"Ignoring non-text configuration value for {key!r}")
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
        # PEP 758: parentheses around multiple exception types are optional on Python 3.14+.
        except EOFError, KeyboardInterrupt:
            return ""

    def get_model_settings_from_user(self) -> None:
        """Optionally ask for an Ollama server endpoint.

        The typed endpoint is validated like any other value: an invalid
        answer is logged and AI recipe creation is disabled (treated as a
        blank answer) rather than stored.
        """
        logger.info("Optionally configure a local AI model so recipes can be created from text, a URL, or an image.")

        endpoint = self._prompt_user("Ollama endpoint (for example http://127.0.0.1:11434). Press Enter to skip: ")
        if not endpoint:
            logger.info("No local model configured; AI recipe creation is disabled")
            self.model_endpoint = ""
            self.all_purpose_model_name = ""
            self.image_analysis_model = ""
            return

        try:
            self.model_endpoint = _normalize_model_endpoint(endpoint)
        except ValueError:
            logger.warning(f"Ignoring invalid endpoint {endpoint!r}; AI recipe creation is disabled")
            self.model_endpoint = ""
            self.all_purpose_model_name = ""
            self.image_analysis_model = ""
            return
        self.all_purpose_model_name = self._prompt_user("All-purpose model name (press Enter to auto-detect from the endpoint): ")
        self.image_analysis_model = self._prompt_user("Image analysis model name (press Enter to auto-detect from the endpoint): ")
        logger.info(
            f"Configured local model endpoint: {self.model_endpoint}"
            f" (all-purpose model: {self.all_purpose_model_name or 'auto-detect'},"
            f" image analysis model: {self.image_analysis_model or 'auto-detect'})"
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
        # Values round-trip through get_config_values(), which stringifies
        # every field; server_port therefore persists as a TOML string,
        # matching the historical on-disk format.
        values = self.get_config_values()
        lines = [
            "# RecipeServer configuration.",
            "# Edit through the Configuration dialog in the app, or by hand here.",
        ]
        for key, value in values.items():
            if key == DICTATION_ENABLED_KEY:
                # Write a real TOML boolean instead of a quoted string.
                lines.append(f"{key} = {value}")
            else:
                lines.append(f"{key} = {_toml_string(value)}")
        # Preserve hand-written auth keys (including secrets) across saves.
        # They are never written by the web API, only read back from TOML.
        for key, value in self._auth_values.items():
            lines.append(f"{key} = {_toml_string(value)}")

        logger.debug(
            f"Saving configuration to {config_file}"
            f" (source={self.source_directory}, endpoint={self.model_endpoint or '(none)'},"
            f" all-purpose model={self.all_purpose_model_name or '(auto)'},"
            f" image analysis model={self.image_analysis_model or '(auto)'},"
            f" server name={self.recipe_server_name!r},"
            f" port={self.server_port}, bind address={self.server_bind_address}, food color={self.food_color},"
            f" dictation={self.dictation_enabled}, transcription endpoint={self.transcription_endpoint},"
            f" transcription model={self.transcription_model}, keep-alive:"
            f" all-purpose={self.all_purpose_model_keep_alive}m, image-analysis={self.image_analysis_model_keep_alive}m, transcription={self.transcription_keep_alive}m,"
            f" timeline retention={self.timeline_retention})"
        )
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("\n".join(lines) + "\n", encoding="UTF-8")

    def _read_and_parse_config(self, config_file: Path) -> tuple[str, dict[str, str]]:
        """Read and parse the config file without modifying it.

        A missing file yields blank settings (defaults apply); the file is
        written by :meth:`_write_config` at the end of the startup flow.
        """
        if not config_file.exists():
            logger.debug(f"No configuration file at {config_file}; using defaults")
            return "", {}

        logger.debug(f"Reading {config_file}")
        config_contents = config_file.read_text(encoding="UTF-8").strip()
        if config_file.suffix == ".toml":
            parsed = self._parse_toml_config(config_contents)
            config_source, settings = ("", {}) if parsed is None else parsed
        else:
            config_source, settings = self._parse_config(config_contents)

        logger.debug(f"Parsed configuration: source={config_source!r}, keys={sorted(settings)}")
        return config_source, settings

    def _resolve_source_directory(self, config_source: str) -> Path:
        source_directory = Path(config_source).expanduser() if config_source else Path()
        if not config_source or not source_directory.is_dir():
            logger.warning(f"Recipe source directory is missing or invalid: {config_source!r}")
            logger.info("Recipes directory not found, please select from the file dialogue")
            source_directory = self.get_source_dir_from_user()
        resolved_source_directory = source_directory.resolve()
        logger.info(f"Using recipe source directory: {resolved_source_directory}")
        return resolved_source_directory

    def _apply_loaded_settings(self, settings: dict[str, str]) -> None:
        for legacy_key, canonical_key in _LEGACY_KEY_MAPPING.items():
            if not settings.get(canonical_key) and settings.get(legacy_key):
                settings[canonical_key] = settings[legacy_key]
        server_name_value = settings.get(RECIPE_SERVER_NAME_KEY, "")
        if server_name_value:
            self.recipe_server_name = server_name_value
        logger.debug(f"Configured recipe server name: {self.recipe_server_name!r}")

        # The setters normalize and validate; an invalid saved value falls
        # back to the default with a logged warning.
        if SERVER_PORT_KEY in settings:
            self.server_port = settings[SERVER_PORT_KEY]
        if SERVER_BIND_ADDRESS_KEY in settings:
            self.server_bind_address = settings[SERVER_BIND_ADDRESS_KEY]
        if FOOD_COLOR_KEY in settings:
            self.food_color = settings[FOOD_COLOR_KEY]
        if DICTATION_ENABLED_KEY in settings:
            self.dictation_enabled = settings[DICTATION_ENABLED_KEY]
        if TRANSCRIPTION_ENDPOINT_KEY in settings:
            self.transcription_endpoint = settings[TRANSCRIPTION_ENDPOINT_KEY]
        if TRANSCRIPTION_MODEL_KEY in settings:
            self.transcription_model = settings[TRANSCRIPTION_MODEL_KEY]
        if ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY in settings:
            self.all_purpose_model_keep_alive = settings[ALL_PURPOSE_MODEL_KEEP_ALIVE_KEY]
        if IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY in settings:
            self.image_analysis_model_keep_alive = settings[IMAGE_ANALYSIS_MODEL_KEEP_ALIVE_KEY]
        if TRANSCRIPTION_KEEP_ALIVE_KEY in settings:
            self.transcription_keep_alive = settings[TRANSCRIPTION_KEEP_ALIVE_KEY]
        if TIMELINE_RETENTION_KEY in settings:
            self.timeline_retention = settings[TIMELINE_RETENTION_KEY]
        logger.debug(
            f"Configured server port: {self.server_port}, bind address: {self.server_bind_address}, food color: {self.food_color},"
            f" dictation: {self.dictation_enabled}, timeline retention: {self.timeline_retention}"
        )
        logger.info(
            f"Transcription (dictation) endpoint: {self.transcription_endpoint}"
            f" (model: {self.transcription_model}, keep-alive: {self.transcription_keep_alive} minutes)"
        )

        if MODEL_ENDPOINT_KEY in settings:
            self.model_endpoint = settings.get(MODEL_ENDPOINT_KEY, "")
            # The legacy singular model_name key remains readable but is
            # normalized to all_purpose_model_name on save.
            self.all_purpose_model_name = settings.get(ALL_PURPOSE_MODEL_NAME_KEY, "")
            self.image_analysis_model = settings.get(IMAGE_ANALYSIS_MODEL_KEY, "")
            logger.info(
                f"Using configured local model endpoint: {self.model_endpoint or '(none)'}"
                f" (all-purpose model: {self.all_purpose_model_name or 'auto-detect'},"
                f" image analysis model: {self.image_analysis_model or 'auto-detect'})"
            )
            return

        logger.debug(f"No {MODEL_ENDPOINT_KEY} key in configuration; prompting the user")
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
                logger.warning(f"Could not remove legacy configuration {config_file}")
            return write_file

        self._write_config(write_file)
        return write_file

    def handle_configuration(self, optional_config_path: Path | None = None):
        config_file = self._resolve_config_file(optional_config_path)
        config_source, settings = self._read_and_parse_config(config_file)
        self._auth_values = {key: settings[key] for key in AUTH_TOML_KEYS if key in settings}

        self.source_directory = self._resolve_source_directory(config_source)
        self._apply_loaded_settings(settings)

        self.load_new_recipe_prompt()
        logger.info(
            f"AI recipe creation is {'enabled' if self.ai_configured else 'disabled'}"
            f" (endpoint={'set' if self.model_endpoint else 'missing'},"
            f" prompt={'set' if self.new_recipe_prompt else 'missing'},"
            f" image prompt={'set' if self.new_recipe_from_image_prompt else 'missing'})"
        )

        self._config_file = self._persist_configuration(config_file)
