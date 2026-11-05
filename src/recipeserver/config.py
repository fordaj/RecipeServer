import sys
from pathlib import Path
from platformdirs import user_data_path
from tkinter import Tk, filedialog
from typing import Optional

from ._logger import logger


MODEL_ENDPOINT_KEY = "model_endpoint"
MODEL_NAME_KEY = "model_name"
NEW_RECIPE_PROMPT_PATH = Path(__file__).resolve().parent / "NewRecipePrompt.md"


class Configuration:
    def __init__(self):
        self.source_directory: Path = Path()
        self.model_endpoint: str = ""
        self.model_name: str = ""
        self.new_recipe_prompt: str = ""

    @property
    def site_directory(self) -> Path:
        return user_data_path("recipe-server", appauthor=False) / "site"

    @property
    def ai_configured(self) -> bool:
        return bool(self.model_endpoint.strip() and self.new_recipe_prompt.strip())

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

        return data_dir / "config.txt"

    @staticmethod
    def _parse_config(contents: str) -> tuple[str, dict[str, str]]:
        """Read the source directory (first bare line) and optional model keys."""
        source_value = ""
        settings: dict[str, str] = {}
        known_keys = {MODEL_ENDPOINT_KEY, MODEL_NAME_KEY}

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

    def get_model_settings_from_user(self) -> None:
        """Optionally ask for an OpenAI-compatible local model endpoint."""
        print(
            "Optionally configure a local AI model so recipes can be created "
            "from text or a URL."
        )

        try:
            endpoint = input(
                "Local model endpoint (for example http://localhost:11434/v1). "
                "Press Enter to skip: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            endpoint = ""

        if not endpoint:
            logger.info("No local model configured; AI recipe creation is disabled")
            self.model_endpoint = ""
            self.model_name = ""
            return

        if "://" not in endpoint:
            endpoint = f"http://{endpoint}"

        try:
            model_name = input(
                "Model name (press Enter to auto-detect from the endpoint): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            model_name = ""

        self.model_endpoint = endpoint
        self.model_name = model_name
        logger.info(
            f"Configured local model endpoint: {endpoint} "
            f"(model: {model_name or 'auto-detect'})"
        )

    def load_new_recipe_prompt(self) -> str:
        """Load the prompt requirements fresh so edits apply on the next run."""
        try:
            prompt = NEW_RECIPE_PROMPT_PATH.read_text(encoding="UTF-8").strip()
        except OSError:
            logger.exception(f"Failed to read new recipe prompt: {NEW_RECIPE_PROMPT_PATH}")
            prompt = ""

        self.new_recipe_prompt = prompt
        logger.info(
            f"Loaded new recipe prompt from {NEW_RECIPE_PROMPT_PATH} "
            f"({len(prompt)} characters)"
        )
        return prompt

    def _write_config(self, config_file: Path) -> None:
        lines = [
            str(self.source_directory),
            f"{MODEL_ENDPOINT_KEY}={self.model_endpoint}",
        ]
        if self.model_name:
            lines.append(f"{MODEL_NAME_KEY}={self.model_name}")

        logger.debug(
            f"Saving configuration to {config_file} "
            f"(source={self.source_directory}, endpoint={self.model_endpoint or '(none)'}, "
            f"model={self.model_name or '(auto)'})"
        )
        config_file.write_text("\n".join(lines) + "\n", encoding="UTF-8")

    def handle_configuration(self, optional_config_txt: Optional[Path] = None):
        config_file = optional_config_txt if optional_config_txt else self.get_config_contents_path_from_user_dir()

        config_file.parent.mkdir(parents=True, exist_ok=True)

        if not config_file.exists():
            logger.debug(f"Creating {config_file}")
            config_file.touch()

        logger.debug(f"Reading {config_file}")
        config_contents = config_file.read_text(encoding="UTF-8").strip()
        config_source, settings = self._parse_config(config_contents)
        logger.debug(
            f"Parsed configuration: source={config_source!r}, "
            f"keys={sorted(settings)}"
        )

        if config_source:
            source_directory = Path(config_source).expanduser()
        else:
            source_directory = Path()

        if not config_source or not source_directory.is_dir():
            logger.warning(
                f"Recipe source directory is missing or invalid: {config_source!r}"
            )
            print("Recipes directory not found, please select from the file dialogue")
            source_directory = self.get_source_dir_from_user()

        self.source_directory = source_directory.resolve()
        logger.info(f"Using recipe source directory: {self.source_directory}")

        if MODEL_ENDPOINT_KEY in settings:
            self.model_endpoint = settings.get(MODEL_ENDPOINT_KEY, "")
            self.model_name = settings.get(MODEL_NAME_KEY, "")
            logger.info(
                f"Using configured local model endpoint: "
                f"{self.model_endpoint or '(none)'} "
                f"(model: {self.model_name or 'auto-detect'})"
            )
        else:
            logger.debug(
                f"No {MODEL_ENDPOINT_KEY} key in configuration; prompting the user"
            )
            self.get_model_settings_from_user()

        self.load_new_recipe_prompt()
        logger.info(
            f"AI recipe creation is {'enabled' if self.ai_configured else 'disabled'} "
            f"(endpoint={'set' if self.model_endpoint else 'missing'}, "
            f"prompt={'set' if self.new_recipe_prompt else 'missing'})"
        )
        self._write_config(config_file)
