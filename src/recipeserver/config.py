
import sys
from pathlib import Path
from platformdirs import user_data_path
from tkinter import Tk, filedialog
from typing import Optional

from ._logger import logger


class Configuration:
    def __init__(self):
        self.source_directory: Path = Path()
        
    @property
    def site_directory(self) -> Path:
        return user_data_path("recipe-server", appauthor=False) / "site"

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

    def handle_configuration(
        self, optional_config_txt: Optional[Path] = None
    ):
        config_file = (
            optional_config_txt
            if optional_config_txt
            else self.get_config_contents_path_from_user_dir()
        )

        config_file.parent.mkdir(parents=True, exist_ok=True)

        if not config_file.exists():
            logger.debug(f"Creating {config_file}")
            config_file.touch()

        logger.info(f"Reading {config_file}")
        config_contents = config_file.read_text(encoding="UTF-8").strip()

        if config_contents:
            source_directory = Path(config_contents).expanduser()
        else:
            source_directory = Path()

        if not config_contents or not source_directory.is_dir():
            print(
                "Recipes directory not found, please select from the file dialogue"
            )
            source_directory = self.get_source_dir_from_user()

        self.source_directory = source_directory.resolve()

        logger.info(f"Saving source directory to {config_file}")
        config_file.write_text(
            str(self.source_directory),
            encoding="UTF-8",
        )
