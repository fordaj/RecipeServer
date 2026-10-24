from pathlib import Path
from .markdown_to_html import MarkdownToHTMLConverter
from .html_embedder import HTMLEmbedder
from .index_html_generator import IndexHTMLGenerator, Recipe
from ._logger import logger, setup_logger
from .config import Configuration
from .server import Server
from .tray import Tray
# from .file_watcher import FileObserver
from threading import Lock, Event
import time

FILE_PATH = Path(__file__)

cfg: Configuration


class Core:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self._regen_lock = Lock()

    def convert_recipe(
        self, markdown: Path
    ) -> tuple[Path, MarkdownToHTMLConverter]:
        working_dir = self.cfg.working_directory.resolve()
        markdown = markdown.resolve()

        if not markdown.is_relative_to(working_dir):
            raise ValueError("Recipe must be inside the working directory")

        if markdown.name != "recipe.md" or not markdown.is_file():
            raise ValueError("Invalid recipe Markdown file")

        html = markdown.with_suffix(".html")
        converter = MarkdownToHTMLConverter(self.cfg)
        converter.convert(markdown, html)

        return html, converter

    def regen(self):
        if not self._regen_lock.acquire(blocking=False):
            logger.debug("Skipping regeneration because one is already running")
            return

        try:
            working_dir = self.cfg.working_directory
            index_generator = IndexHTMLGenerator(self.cfg)

            for markdown in working_dir.rglob("recipe.md"):
                if not markdown.is_file():
                    continue

                html, converter = self.convert_recipe(markdown)
                index_generator.add(Recipe(converter.metadata, html))

            index_generator.convert()

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

    tray.run()

    logger.debug("RecipeServer is running.")

    try:
        while not shutdown_event.wait():
            pass
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        logger.info("Shutting down RecipeServer...")
        server.stop()
        tray.icon.stop()
        logger.info("RecipeServer stopped.")
