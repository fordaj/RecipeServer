import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from shutil import copy2, copytree, rmtree
from threading import Event, Lock

from ._logger import logger, LogLevel
from .config import Configuration
from .image_handler import IMAGE_EXTENSIONS
from .index_html_generator import IndexHTMLGenerator, Recipe
from .markdown_to_html import MarkdownToHTMLConverter
from .server import Server
from .tray import Tray

# Recipe conversion is mostly I/O (reading Markdown, copying images) with some
# CPU-bound rendering, so even a low-core machine benefits from a floor of
# DEFAULT_WORKERS threads; MAX_WORKERS caps thread growth on large machines.
DEFAULT_WORKERS = 8
MAX_WORKERS = 16

# How often the non-macOS shutdown path checks whether the tray asked to quit.
QUIT_POLL_INTERVAL_SECONDS = 0.25


def get_worker_count() -> int:
    cpu_count = os.process_cpu_count() or 1

    return min(
        MAX_WORKERS,
        max(DEFAULT_WORKERS, cpu_count),
    )


class Core:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self._regen_lock = Lock()
        self._recipes: dict[Path, Recipe] = {}

    @staticmethod
    def get_assets_directory() -> Path:
        if getattr(sys, "frozen", False):
            # PyInstaller extracts bundled assets here.
            return Path(sys._MEIPASS) / "recipeserver" / "assets"

        # Local development: src/recipeserver/assets
        return Path(__file__).resolve().parent / "assets"

    @staticmethod
    def copy_assets(site_directory: Path) -> None:
        assets_directory = Core.get_assets_directory()
        destination = site_directory / "assets"
        copytree(assets_directory, destination, dirs_exist_ok=True)
        logger.debug(f'Copied "{assets_directory}" to "{destination}"')

    def convert_recipe(self, markdown: Path) -> tuple[Path, MarkdownToHTMLConverter]:
        working_dir = self.cfg.source_directory.resolve()
        markdown = markdown.resolve()

        if not markdown.is_relative_to(working_dir):
            raise ValueError("Recipe must be inside the working directory")

        if markdown.name != "recipe.md" or not markdown.is_file():
            raise ValueError("Invalid recipe Markdown file")

        # Preserve the source directory structure under site/.
        relative_path = markdown.relative_to(working_dir)
        html = (self.cfg.site_directory / relative_path).with_suffix(".html")
        html.parent.mkdir(parents=True, exist_ok=True)

        converter = MarkdownToHTMLConverter(self.cfg)
        converter.convert(markdown, html)

        # Copy images over.
        for image in markdown.parent.iterdir():
            if image.is_file() and image.suffix.lower() in IMAGE_EXTENSIONS:
                copy2(image, html.parent / image.name)

        return html, converter

    def _update_index(self) -> None:
        """Regenerate index.html using the latest known recipe data."""
        index_generator = IndexHTMLGenerator(self.cfg)

        for recipe in self._recipes.values():
            index_generator.add(recipe)

        index_generator.convert()

    def on_markdown_save(self, markdown: Path) -> None:
        """Convert one recipe and update the index."""
        with self._regen_lock:
            markdown = markdown.resolve()

            html, converter = self.convert_recipe(markdown)

            self._recipes[markdown] = Recipe(converter.metadata, html, converter.title)

            self._update_index()

            logger.info(f'Updated recipe and index: "{markdown}"')

    def regen(self):
        if not self._regen_lock.acquire(blocking=False):
            logger.debug("Skipping regeneration because one is already running")
            return

        try:
            self._regen_locked()
        finally:
            self._regen_lock.release()

    def on_recipes_deleted(self, markdown_paths) -> None:
        """Drop deleted recipes from the index and remove their pages."""
        paths = list(markdown_paths)
        with self._regen_lock:
            for markdown in paths:
                markdown = markdown.resolve()
                recipe = self._recipes.pop(markdown, None)
                if recipe is not None:
                    html = recipe.html_file
                else:
                    relative = markdown.relative_to(self.cfg.source_directory.resolve())
                    html = (self.cfg.site_directory / relative).with_suffix(".html")
                html.unlink(missing_ok=True)
            self._update_index()
            logger.info(f"Removed {len(paths)} recipe(s) from index")

    def on_config_save(self):
        """Rebuild the whole site after a configuration change."""
        with self._regen_lock:
            self._regen_locked()
            logger.info("Regenerated site after configuration change")

    def _regen_locked(self):
        """Full site rebuild; caller must hold ``_regen_lock``."""
        start = time.perf_counter()
        working_dir = self.cfg.source_directory.resolve()

        if self.cfg.site_directory.exists():
            logger.debug(f'Deleting "{self.cfg.site_directory}"')
            rmtree(self.cfg.site_directory)

        self.cfg.site_directory.mkdir(parents=True)
        logger.debug(f'Created "{self.cfg.site_directory}"')
        self.copy_assets(self.cfg.site_directory)

        markdown_files = [markdown for markdown in working_dir.rglob("recipe.md") if markdown.is_file()]

        self._recipes.clear()

        worker_count = 0
        if markdown_files:
            worker_count = min(get_worker_count(), len(markdown_files))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {executor.submit(self.convert_recipe, markdown): markdown for markdown in markdown_files}

                for future in as_completed(futures):
                    markdown = futures[future]
                    try:
                        html, converter = future.result()
                    except Exception:
                        # One broken recipe should not prevent the rest of the site from building.
                        logger.exception(f'Failed to convert recipe "{markdown}", skipping it')
                        continue

                    self._recipes[markdown.resolve()] = Recipe(
                        converter.metadata,
                        html,
                        converter.title,
                    )

        self._update_index()

        logger.info(f"Regenerated site with {worker_count} workers in {time.perf_counter() - start:.1f}s")


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-l",
        "--log-level",
        type=str.upper,
        choices=[level.name for level in LogLevel],
        default=LogLevel.INFO.name,
        metavar="LEVEL",
        help="Logging verbosity (default: INFO)",
    )

    return parser.parse_args()


def main(cfg: Configuration):
    core = Core(cfg)
    core.regen()

    server = Server(
        cfg,
        on_markdown_saved=core.on_markdown_save,
        on_config_saved=core.on_config_save,
        on_recipes_deleted=core.on_recipes_deleted,
    )
    server.start()

    shutdown_event = Event()
    tray = Tray(server, on_quit=shutdown_event.set)

    try:
        if sys.platform == "darwin":
            # macOS requires the tray icon to run on the main thread, so run()
            # blocks here until the tray quits; Ctrl+C raises KeyboardInterrupt.
            tray.run()
        else:
            # Detach the tray so this thread stays free to notice a quit request;
            # Windows does not deliver KeyboardInterrupt reliably in this state.
            tray.run_detached()

            while not shutdown_event.wait(QUIT_POLL_INTERVAL_SECONDS):
                pass

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        logger.info("Shutting down RecipeServer...")
        shutdown_event.set()
        tray.stop()
        server.stop()
        logger.info("RecipeServer stopped.")
