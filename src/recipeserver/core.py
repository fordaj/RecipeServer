from pathlib import Path
from .markdown_to_html import MarkdownToHTMLConverter
from .html_embedder import HTMLEmbedder
from .index_html_generator import IndexHTMLGenerator, Recipe
from ._logger import logger, setup_logger
from .config import Configuration
from .server import Server
from .tray import Tray
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Event
from shutil import rmtree, copytree, copy2
import time, sys, os

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


class Core:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self._regen_lock = Lock()

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

        # COPY IMAEGES OVER
        for image in markdown.parent.iterdir():
            if image.is_file() and image.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}:
                copy2(image, html.parent / image.name)

        return html, converter

    def regen(self):
        start = time.perf_counter()
        if not self._regen_lock.acquire(blocking=False):
            logger.debug("Skipping regeneration because one is already running")
            return

        try:
            working_dir = self.cfg.source_directory.resolve()

            if self.cfg.site_directory.exists():
                logger.debug(f'Deleting "{self.cfg.site_directory}"')
                rmtree(self.cfg.site_directory)

            self.cfg.site_directory.mkdir(parents=True)
            logger.debug(f'Created "{self.cfg.site_directory}"')
            self.copy_assets(self.cfg.site_directory)

            markdown_files = [markdown for markdown in working_dir.rglob("recipe.md") if markdown.is_file()]

            index_generator = IndexHTMLGenerator(self.cfg)

            if markdown_files:
                with ThreadPoolExecutor(max_workers=min(NUM_WORKERS, len(markdown_files))) as executor:
                    results = executor.map(
                        self.convert_recipe,
                        markdown_files,
                    )

                    for html, converter in results:
                        index_generator.add(Recipe(converter.metadata, html))

            index_generator.convert()
            logger.info(f"Regenerated site with {NUM_WORKERS} workers in {time.perf_counter() - start:.1f}s")
        finally:
            self._regen_lock.release()


def main(_cfg: Configuration):
    cfg = _cfg
    # observer = FileObserver()
    core = Core(cfg)

    # def on_file_changed(path: Path):
    #     print(path)
    #     # observer.stop()

    #     core.regen()

    #     # time.sleep(2)

    #     # observer.start()

    # observer.setup([cfg.working_directory], on_file_changed=on_file_changed)
    # observer.start()
    core.regen()

    server = Server(cfg, on_markdown_saved=core.convert_recipe)
    server.start()

    shutdown_event = Event()
    tray = Tray(server, on_quit=shutdown_event.set)

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
        tray.stop()
        server.stop()
        logger.info("RecipeServer stopped.")
