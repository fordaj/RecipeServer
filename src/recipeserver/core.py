from pathlib import Path
from collections.abc import Sequence
from .image_handler import IMAGE_EXTENSIONS
from .markdown_to_html import MarkdownToHTMLConverter
from .index_html_generator import IndexHTMLGenerator, Recipe
from .file_watcher import ChangeKind, FileChange, LibraryWatcher
from ._logger import logger, setup_logger, LogLevel
from .config import Configuration
from .server import Server
from .tray import Tray
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event
from shutil import rmtree, copytree, copy2
import time, sys, os, argparse

FILE_PATH = Path(__file__)
DEFAULT_WORKERS = 8
MAX_WORKERS = 16


def get_worker_count() -> int:

    cpu_count = os.process_cpu_count() or 1

    return min(
        MAX_WORKERS,
        max(DEFAULT_WORKERS, cpu_count),
    )


NUM_WORKERS = get_worker_count()


cfg: Configuration


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None

    return (stat.st_mtime_ns, stat.st_size)


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


class Core:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self._regen_lock = Lock()
        self._recipes: dict[Path, Recipe] = {}
        # Signatures of recipe.md files already reflected in the generated site.
        # They keep the watcher from reacting to the app's own saves.
        self._source_signatures: dict[Path, tuple[int, int]] = {}
        self._revision_lock = Lock()
        self._revision = 0

    @property
    def revision(self) -> int:
        with self._revision_lock:
            return self._revision

    def _increment_revision(self) -> int:
        with self._revision_lock:
            self._revision += 1
            return self._revision

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

    def _html_path(self, markdown: Path) -> Path | None:
        """Map a source recipe path to its generated HTML path."""
        try:
            relative_path = markdown.resolve().relative_to(
                self.cfg.source_directory.resolve()
            )
        except ValueError:
            return None

        return (self.cfg.site_directory / relative_path).with_suffix(".html")

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

        # Copy images over, and prune images that no longer exist in the source
        # so that deleting or renaming a hero image updates the hero/accent.
        source_images = {
            image.name: image
            for image in markdown.parent.iterdir()
            if image.is_file() and _is_image(image)
        }

        for generated in html.parent.iterdir():
            if (
                generated.is_file()
                and _is_image(generated)
                and generated.name not in source_images
            ):
                generated.unlink()
                logger.debug(f'Removed stale generated image "{generated}"')

        for name, image in source_images.items():
            copy2(image, html.parent / name)

        return html, converter

    def _update_index(self) -> None:
        """Regenerate index.html using the latest known recipe data."""
        index_generator = IndexHTMLGenerator(self.cfg)

        for recipe in self._recipes.values():
            index_generator.add(recipe)

        index_generator.convert()

    def _record_signature(
        self,
        markdown: Path,
        signature: tuple[int, int] | None = None,
    ) -> None:
        if signature is None:
            signature = _file_signature(markdown)

        if signature is None:
            self._source_signatures.pop(markdown, None)
        else:
            self._source_signatures[markdown] = signature

    def _recipe_changed(self, markdown: Path) -> bool:
        if markdown not in self._recipes:
            return True

        return self._source_signatures.get(markdown) != _file_signature(markdown)

    def _remove_recipe_locked(self, markdown: Path) -> None:
        """Forget a recipe and remove its generated page and images."""
        markdown = markdown.resolve()
        self._recipes.pop(markdown, None)
        self._source_signatures.pop(markdown, None)

        html = self._html_path(markdown)
        if html is None:
            return

        try:
            html.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception(f'Failed to delete generated page "{html}"')

        try:
            for generated in html.parent.iterdir():
                if generated.is_file() and _is_image(generated):
                    generated.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception(f'Failed to clean generated images in "{html.parent}"')

        # Remove now-empty directories, but never the site root itself.
        site_directory = self.cfg.site_directory.resolve()
        parent = html.parent.resolve()

        while parent != site_directory and parent.is_relative_to(site_directory):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def _refresh_recipe_locked(self, markdown: Path) -> bool:
        """Refresh one recipe. Returns True when the site content changed."""
        markdown = markdown.resolve()
        signature = _file_signature(markdown)

        try:
            html, converter = self.convert_recipe(markdown)
        except Exception:
            logger.exception(
                f'Failed to convert recipe "{markdown}", removing its generated page'
            )
            self._remove_recipe_locked(markdown)
            return True

        self._recipes[markdown] = Recipe(
            converter.metadata,
            html,
            converter.title,
        )
        self._record_signature(markdown, signature)
        return True

    def on_markdown_save(self, markdown: Path) -> None:
        """Convert one recipe and update the index."""
        with self._regen_lock:
            markdown = markdown.resolve()
            signature = _file_signature(markdown)

            html, converter = self.convert_recipe(markdown)

            self._recipes[markdown] = Recipe(converter.metadata, html, converter.title)
            self._record_signature(markdown, signature)

            self._update_index()
            self._increment_revision()

            logger.info(f'Updated recipe and index: "{markdown}"')

    def _full_rebuild_locked(self) -> None:
        """Rebuild every generated file. Caller must hold ``_regen_lock``."""
        start = time.perf_counter()
        working_dir = self.cfg.source_directory.resolve()

        if self.cfg.site_directory.exists():
            logger.debug(f'Deleting "{self.cfg.site_directory}"')
            rmtree(self.cfg.site_directory)

        self.cfg.site_directory.mkdir(parents=True)
        logger.debug(f'Created "{self.cfg.site_directory}"')
        self.copy_assets(self.cfg.site_directory)

        markdown_files = [
            markdown
            for markdown in working_dir.rglob("recipe.md")
            if markdown.is_file()
        ]
        signatures = {
            markdown.resolve(): _file_signature(markdown)
            for markdown in markdown_files
        }

        self._recipes.clear()
        self._source_signatures.clear()

        if markdown_files:
            with ThreadPoolExecutor(
                max_workers=min(NUM_WORKERS, len(markdown_files))
            ) as executor:
                futures = {
                    executor.submit(self.convert_recipe, markdown): markdown
                    for markdown in markdown_files
                }

                for future in as_completed(futures):
                    markdown = futures[future]
                    try:
                        html, converter = future.result()
                    except Exception:
                        # One broken recipe should not prevent the rest of the site from building.
                        logger.exception(
                            f'Failed to convert recipe "{markdown}", skipping it'
                        )
                        continue

                    markdown = markdown.resolve()
                    self._recipes[markdown] = Recipe(
                        converter.metadata,
                        html,
                        converter.title,
                    )
                    self._record_signature(markdown, signatures.get(markdown))

        self._update_index()

        logger.info(
            f"Regenerated site with {NUM_WORKERS} workers "
            f"in {time.perf_counter() - start:.1f}s"
        )

    def regen(self):
        """Rebuild the site unless another regeneration is already running."""
        if not self._regen_lock.acquire(blocking=False):
            logger.debug("Skipping regeneration because one is already running")
            return

        try:
            self._full_rebuild_locked()
            self._increment_revision()
        finally:
            self._regen_lock.release()

    def refresh_all(self) -> None:
        """Rebuild the whole site, waiting for any in-flight refresh first."""
        with self._regen_lock:
            self._full_rebuild_locked()
            self._increment_revision()

    def handle_file_changes(self, changes: Sequence[FileChange]) -> None:
        """Apply a batch of external filesystem changes to the generated site."""
        if not changes:
            return

        with self._regen_lock:
            if any(change.is_directory for change in changes):
                logger.info("Directory change detected; rebuilding the whole site")
                self._full_rebuild_locked()
                self._increment_revision()
                return

            recipes_to_remove: set[Path] = set()
            recipes_to_refresh: dict[Path, bool] = {}

            def refresh(path: Path, *, force: bool) -> None:
                markdown = (path / "recipe.md").resolve()
                recipes_to_refresh[markdown] = (
                    recipes_to_refresh.get(markdown, False) or force
                )

            for change in changes:
                if change.kind in (ChangeKind.DELETED, ChangeKind.MOVED):
                    old_path = change.old_path or change.path
                    if old_path.name == "recipe.md":
                        recipes_to_remove.add(old_path.resolve())
                        recipes_to_refresh.pop(old_path.resolve(), None)
                    elif _is_image(old_path):
                        if (old_path.parent / "recipe.md").is_file():
                            refresh(old_path.parent, force=True)

                if change.kind in (
                    ChangeKind.CREATED,
                    ChangeKind.MODIFIED,
                    ChangeKind.MOVED,
                ):
                    new_path = change.path
                    if new_path.name == "recipe.md":
                        markdown = new_path.resolve()
                        force = change.kind is ChangeKind.CREATED or self._recipe_changed(
                            markdown
                        )
                        recipes_to_remove.discard(markdown)
                        refresh(new_path.parent, force=force)
                    elif _is_image(new_path):
                        if (new_path.parent / "recipe.md").is_file():
                            refresh(new_path.parent, force=True)

            changed = False

            for markdown in sorted(recipes_to_remove):
                html = self._html_path(markdown)
                existed = markdown in self._recipes or (
                    html is not None and html.exists()
                )
                self._remove_recipe_locked(markdown)
                if existed:
                    changed = True

            for markdown, force in sorted(recipes_to_refresh.items()):
                if markdown in recipes_to_remove:
                    continue

                if not markdown.is_file():
                    self._remove_recipe_locked(markdown)
                    changed = True
                    continue

                if not force and not self._recipe_changed(markdown):
                    continue

                if self._refresh_recipe_locked(markdown):
                    changed = True

            if not changed:
                logger.debug("Ignoring filesystem changes that did not affect the site")
                return

            self._update_index()
            self._increment_revision()
            logger.info(
                f"Applied {len(changes)} filesystem change(s); "
                f"revision {self.revision}"
            )


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


def main(_cfg: Configuration):
    cfg = _cfg
    core = Core(cfg)
    core.regen()

    watcher = LibraryWatcher(
        cfg.source_directory,
        core.handle_file_changes,
        site_directory=cfg.site_directory,
    )
    watcher.start()

    server = Server(
        cfg,
        on_markdown_saved=core.on_markdown_save,
        revision_getter=lambda: core.revision,
    )
    server.start()

    shutdown_event = Event()
    tray = Tray(server, on_quit=shutdown_event.set, on_refresh=core.refresh_all)

    try:
        if sys.platform == "darwin":  # Mac requires tray.run() to work at all and is KeyboardInterrupt-able
            tray.run()  # TODO: KeyboardInterrupt isn't caught on Mac either!
        else:  # Windows won't handle KeyboardInterrupts properly unless you run detached
            tray.run_detached()

            while not shutdown_event.wait(0.25):
                pass

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        logger.info("Shutting down RecipeServer...")
        shutdown_event.set()
        watcher.stop()
        tray.stop()
        server.stop()
        logger.info("RecipeServer stopped.")
