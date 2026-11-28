import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from shutil import copy2, copytree, rmtree
from threading import Event, Lock

from ._logger import logger, LogLevel
from .auth_config import AuthConfigError, load_auth_settings
from .authorization import AuthManager
from .config import Configuration
from .oidc import OIDCError
from .history import write_file_atomic
from .image_handler import IMAGE_EXTENSIONS
from .index_html_generator import IndexHTMLGenerator, Recipe
from .markdown_to_html import MarkdownToHTMLConverter
from .recipe_paths import RECIPE_FILENAME, iter_recipe_files
from .recipe_utils import extract_recipe_id, new_recipe_id, set_recipe_id
from .retention import get_retention_manager
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
        # Populated by `_regen_locked()`; phase timings in seconds. Empty until
        # the first regen completes. Scale-testing harness reads this.
        self.last_regen_timings: dict[str, float] = {}

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

        if markdown.name != RECIPE_FILENAME or not markdown.is_file():
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
        # A configuration save may have switched the retention policy:
        # apply it in the background. When the policy is Unlimited this is a
        # no-op, and pruning never runs for that policy at all.
        get_retention_manager().request_full_scan(force=True)

    @staticmethod
    def _ensure_recipe_ids(markdown_files: list[Path]) -> None:
        """Give every recipe a unique ``recipe_id``, assigning them in place.

        Existing recipes that already carry a valid identifier keep it.
        Recipes without one get a fresh UUIDv4 injected into their front
        matter (or a new block prepended), preserving the rest of the file
        byte-for-byte. Duplicate identifiers — such as when a recipe file is
        copied — are resolved deterministically: the path that sorts first
        keeps the identifier, the copies get fresh ones. Identity assignments
        are not content modifications, so they create no history snapshots.
        """
        owners: dict[str, list[Path]] = {}
        missing: list[Path] = []
        contents: dict[Path, str] = {}

        for markdown in sorted(markdown_files):
            try:
                content = markdown.read_text(encoding="utf-8")
            except OSError:
                logger.exception(f'Unable to read recipe "{markdown}" to check its recipe_id')
                continue
            contents[markdown] = content
            recipe_id = extract_recipe_id(content)
            if recipe_id is None:
                missing.append(markdown)
            else:
                owners.setdefault(recipe_id, []).append(markdown)

        assignments: dict[Path, str] = {markdown: new_recipe_id() for markdown in missing}
        for paths in owners.values():
            if len(paths) <= 1:
                continue
            # The first (sorted) holder keeps the id; the copies get fresh ones.
            for duplicate in sorted(paths)[1:]:
                assignments[duplicate] = new_recipe_id()

        for markdown, recipe_id in assignments.items():
            try:
                write_file_atomic(markdown, set_recipe_id(contents[markdown], recipe_id))
            except OSError:
                logger.exception(f'Unable to assign a recipe_id to "{markdown}"')

        if assignments:
            logger.info(f"Assigned recipe_id to {len(assignments)} recipe(s)")

    def _regen_locked(self):
        """Full site rebuild; caller must hold ``_regen_lock``."""
        start = time.perf_counter()
        timings: dict[str, float] = {}
        working_dir = self.cfg.source_directory.resolve()

        if self.cfg.site_directory.exists():
            logger.debug(f'Deleting "{self.cfg.site_directory}"')
            rmtree(self.cfg.site_directory)

        self.cfg.site_directory.mkdir(parents=True)
        logger.debug(f'Created "{self.cfg.site_directory}"')
        assets_start = time.perf_counter()
        self.copy_assets(self.cfg.site_directory)
        timings["assets_copy"] = time.perf_counter() - assets_start

        markdown_files = iter_recipe_files(working_dir)

        self._ensure_recipe_ids(markdown_files)

        self._recipes.clear()

        worker_count = 0
        conversion_start = time.perf_counter()
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

        timings["recipe_conversion"] = time.perf_counter() - conversion_start

        index_start = time.perf_counter()
        self._update_index()
        timings["index_build"] = time.perf_counter() - index_start
        timings["total"] = time.perf_counter() - start
        self.last_regen_timings = timings

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
    # Authentication is validated and the provider is discovered before the
    # listener opens. A broken OIDC configuration must fail loudly, never fall
    # back to an unauthenticated server.
    try:
        auth_values = cfg.get_auth_values() if hasattr(cfg, "get_auth_values") else {}
        auth_settings = load_auth_settings(auth_values)
        auth_manager = AuthManager(auth_settings) if auth_settings.enabled else None
    except (AuthConfigError, OIDCError) as exc:
        logger.error(f"Authentication configuration error: {exc}")
        sys.exit(1)

    core = Core(cfg)
    core.regen()

    # Timeline retention runs in the background: an immediate pass plus a
    # periodic sweep, and a throttled pass after each save.
    retention_manager = get_retention_manager()
    retention_manager.configure(cfg)
    retention_manager.start()

    server_kwargs = {
        "on_markdown_saved": core.on_markdown_save,
        "on_config_saved": core.on_config_save,
        "on_recipes_deleted": core.on_recipes_deleted,
    }
    if auth_manager is not None:
        server_kwargs["auth"] = auth_manager
    server = Server(cfg, **server_kwargs)
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
        retention_manager.stop()
        logger.info("RecipeServer stopped.")
