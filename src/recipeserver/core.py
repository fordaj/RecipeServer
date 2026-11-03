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
import hashlib
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


SourceSignature = tuple[int, int] | bytes


def _stat_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None

    return (stat.st_mtime_ns, stat.st_size)


def _recipe_signature(path: Path) -> bytes | None:
    """Hash recipe text so metadata-only touches do not trigger a refresh."""
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        return None


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _recipe_source_signatures(markdown: Path) -> dict[Path, SourceSignature]:
    """Snapshot the recipe and its hero candidate files before conversion."""
    signatures: dict[Path, SourceSignature] = {}

    signature = _recipe_signature(markdown)
    if signature is not None:
        signatures[markdown] = signature

    try:
        images = [
            path
            for path in markdown.parent.iterdir()
            if path.is_file() and _is_image(path) and not path.name.startswith(".")
        ]
    except OSError:
        images = []

    for image in images:
        image_signature = _stat_signature(image)
        if image_signature is not None:
            signatures[image] = image_signature

    return signatures


class Core:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self._regen_lock = Lock()
        self._recipes: dict[Path, Recipe] = {}
        # Signatures of source files already reflected in the generated site.
        # They keep the watcher from reacting to the app's own saves and to
        # metadata-only filesystem events.
        self._source_signatures: dict[Path, SourceSignature] = {}
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
            if image.is_file() and _is_image(image) and not image.name.startswith(".")
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

    def _record_recipe_signatures(
        self,
        markdown: Path,
        signatures: dict[Path, SourceSignature] | None = None,
    ) -> None:
        if signatures is None:
            signatures = _recipe_source_signatures(markdown)

        # Replace the previous snapshot for this recipe directory. Direct
        # children only, so nested recipes keep their own signatures.
        directory = markdown.parent
        for path in [path for path in self._source_signatures if path.parent == directory]:
            del self._source_signatures[path]

        self._source_signatures.update(signatures)

    def _recipe_changed(self, markdown: Path) -> bool:
        if markdown not in self._recipes:
            return True

        return self._source_signatures.get(markdown) != _recipe_signature(markdown)

    def _image_changed(self, image: Path) -> bool:
        return self._source_signatures.get(image) != _stat_signature(image)

    def _remove_recipe_locked(self, markdown: Path) -> None:
        """Forget a recipe and remove its generated page and images."""
        markdown = markdown.resolve()
        self._recipes.pop(markdown, None)

        directory = markdown.parent
        for path in [path for path in self._source_signatures if path.parent == directory]:
            del self._source_signatures[path]

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
        signatures = _recipe_source_signatures(markdown)

        try:
            html, converter = self.convert_recipe(markdown)
        except Exception:
            if not markdown.is_file():
                logger.info(
                    f'Recipe "{markdown}" disappeared during refresh; removing its page'
                )
                self._remove_recipe_locked(markdown)
                return True

            # A locked, partially written, or temporarily invalid file should
            # not erase the last good page. The next event retries because the
            # stored signature is left untouched.
            logger.exception(
                f'Failed to refresh recipe "{markdown}", keeping the last generated version'
            )
            return False

        self._recipes[markdown] = Recipe(
            converter.metadata,
            html,
            converter.title,
        )
        self._record_recipe_signatures(markdown, signatures)
        return True

    def on_markdown_save(self, markdown: Path) -> None:
        """Convert one recipe and update the index."""
        with self._regen_lock:
            markdown = markdown.resolve()
            signatures = _recipe_source_signatures(markdown)

            html, converter = self.convert_recipe(markdown)

            self._recipes[markdown] = Recipe(converter.metadata, html, converter.title)
            self._record_recipe_signatures(markdown, signatures)

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
            markdown.resolve(): _recipe_source_signatures(markdown.resolve())
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
                    self._record_recipe_signatures(markdown, signatures.get(markdown))

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

    def _directory_change_requires_rebuild(self, change: FileChange) -> bool:
        """Decide whether a directory event can affect the generated site.

        Creating or moving a directory can bring or take away a recipe tree, so
        those stay conservative. Deleting an unrelated directory (caches, temp
        folders, editor scratch space) must not rebuild the whole site.
        """
        if change.kind is not ChangeKind.DELETED:
            return change.kind in (ChangeKind.CREATED, ChangeKind.MOVED)

        return any(
            markdown.is_relative_to(change.path) for markdown in self._recipes
        )

    def handle_file_changes(self, changes: Sequence[FileChange]) -> None:
        """Apply a batch of external filesystem changes to the generated site."""
        if not changes:
            return

        with self._regen_lock:
            directory_changes = [change for change in changes if change.is_directory]

            if any(
                self._directory_change_requires_rebuild(change)
                for change in directory_changes
            ):
                logger.info("Directory change detected; rebuilding the whole site")
                self._full_rebuild_locked()
                self._increment_revision()
                return

            file_changes = [change for change in changes if not change.is_directory]

            if not file_changes:
                logger.debug(
                    "Ignoring directory changes that did not affect any recipe"
                )
                return

            recipes_to_remove: set[Path] = set()
            recipes_to_refresh: dict[Path, bool] = {}

            def refresh(path: Path, *, force: bool) -> None:
                markdown = (path / "recipe.md").resolve()
                recipes_to_refresh[markdown] = (
                    recipes_to_refresh.get(markdown, False) or force
                )

            for change in file_changes:
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
                            # Image events include metadata-only notifications.
                            # Only regenerate when the image actually changed.
                            force = (
                                change.kind is not ChangeKind.MODIFIED
                                or self._image_changed(new_path)
                            )
                            refresh(new_path.parent, force=force)

            changed = False

            for markdown in sorted(recipes_to_remove):
                if markdown.is_file():
                    # The file reappeared after its delete event, as happens
                    # with some editors' atomic save. Treat it as an update
                    # instead of briefly deleting the recipe from the site.
                    recipes_to_remove.discard(markdown)
                    if self._recipe_changed(markdown):
                        recipes_to_refresh[markdown] = True
                    continue

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
