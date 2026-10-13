import sys
from ._logger import logger
from pathlib import Path
from platformdirs import user_data_path
from tkinter import Tk, filedialog
from typing import Optional


class Configuration:
    def __init__(self):
        self.working_directory: Path = Path()

    def get_working_dir_from_user(self) -> Path:
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

        if selected is None:
            logger.info("User cancelled operation, exiting")
            sys.exit(0)

        return Path(selected)

    def get_config_contents_path_from_user_dir(self) -> Path:
        DATA_DIR: Path = user_data_path("recipe-server", appauthor=False)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        return DATA_DIR / "config.txt"

    def handle_configuration(self, optional_config_txt: Optional[Path] = None):
        # Read config
        if optional_config_txt:
            config_file = optional_config_txt
        else:
            config_file = self.get_config_contents_path_from_user_dir()

        if not config_file.exists():
            logger.debug(f"Creating {config_file}")
            config_file.touch()

        logger.info(f"Reading {config_file}")
        config_contents = config_file.read_text(encoding="UTF-8", newline="\n")

        # Load values
        self.working_directory = Path(config_contents)

        # Handle missing values
        if config_contents == "" or not self.working_directory.is_dir():
            print("Recipes directory not found, please select from the file dialogue")
            self.working_directory = self.get_working_dir_from_user()

        # Save values
        config_contents = str(self.working_directory.absolute())

        # Write config
        config_file.write_text(config_contents, encoding="UTF-8", newline="\n")
