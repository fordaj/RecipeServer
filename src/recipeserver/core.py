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
from .https_setup import CaddyServer, HttpsSetupError, export_root_ca, start_https
from .image_handler import IMAGE_EXTENSIONS
from .index_html_generator import IndexHTMLGenerator, Recipe
from .markdown_to_html import MarkdownToHTMLConverter
from .server import Server
from .transcriber import stop_transcriber
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
        self._server: Server | None = None
        self._caddy: CaddyServer | None = None
        # Port the embedded server was bound to when Caddy was created;
        # Caddy proxies there, so a change means Caddy must re-target it.
        self._caddy_bind_port: int | None = None

    def attach_server(self, server: Server) -> None:
        """Let the core manage the HTTPS front-end around *server*.

        The embedded server can change its serving mode at runtime, and the
        Caddy instance that fronts it depends on that mode, so both are
        managed together — see ``_reconcile_https``.
        """
        self._server = server

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
        if not getattr(self.cfg, "dictation_enabled", True):
            # Dictation was turned off: release the whisper-server (and its
            # model) instead of letting it linger.
            stop_transcriber()
        self._reconcile_https()

    def start_caddy(self, force: bool = False) -> CaddyServer:
        """(Re)create the Caddy instance fronting the embedded server.

        A running Caddy proxying to the server's current internal port is
        kept; anything else is replaced so the proxy always targets the
        right port.
        """
        if self._server is None:
            raise HttpsSetupError("The server is not attached to the core")
        bind_port = self._server.bind_port
        if bind_port <= 0:
            raise HttpsSetupError("The embedded server is not running")
        if not force and self._caddy is not None and self._caddy.is_running and self._caddy_bind_port == bind_port:
            return self._caddy
        self.stop_caddy()
        self._caddy = start_https(self.cfg, bind_port)
        self._caddy_bind_port = bind_port
        # Publish the public root CA next to the site so other devices can
        # install it; best effort — the site works without it.
        export_root_ca(self.cfg.site_directory)
        return self._caddy

    def stop_caddy(self) -> None:
        if self._caddy is not None:
            self._caddy.stop()
            self._caddy = None
        self._caddy_bind_port = None

    def start_all(self) -> None:
        """Start the site (the embedded server and Caddy, when enabled)."""
        if self._server is None:
            return
        self._server.start()
        if getattr(self.cfg, "https_enabled", False):
            try:
                self.start_caddy()
            except Exception:
                # Roll back to a fully stopped site rather than leaving
                # the embedded server running where nobody can reach it.
                self._server.stop()
                raise

    def stop_all(self) -> None:
        """Stop the site (Caddy first, then the embedded server)."""
        self.stop_caddy()
        if self._server is not None:
            self._server.stop()

    def _reconcile_https(self) -> None:
        """Match the running Caddy/server to ``cfg.https_enabled``.

        Enabling HTTPS moves the embedded server to an ephemeral loopback
        port and binds Caddy to the configured port; disabling it stops
        Caddy and returns the configured port to plain HTTP. Both elements
        are rebuilt against each other so the port Caddy proxies to always
        matches the server's current one.
        """
        server = self._server
        if server is None:
            return
        desired = bool(getattr(self.cfg, "https_enabled", False))
        # The order matters: Caddy and the embedded server cannot both
        # hold the configured port. Enabling moves Python out of the way
        # first; disabling makes Caddy release it first.
        if desired:
            # set_https() re-binds a running listener only when the mode
            # changed; with the server stopped it just records the mode.
            server.set_https(True)
            if server.is_running:
                try:
                    self.start_caddy()
                except Exception:
                    # Put plain HTTP back on the configured port and stop
                    # the half-started front-end.
                    self.stop_caddy()
                    server.set_https(False)
                    raise
            else:
                # Nothing to proxy to; the tray restarts both together.
                self.stop_caddy()
        else:
            # Caddy holds the configured port; it must release it before
            # the embedded server can bind it again.
            self.stop_caddy()
            server.set_https(False)

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

        if getattr(self.cfg, "https_enabled", False):
            # Best effort: the site stays usable when the root CA cannot
            # be published, it just means other devices cannot install it
            # from /rootCA.pem.
            export_root_ca(self.cfg.site_directory)

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
    core.attach_server(server)
    server.start()

    if getattr(cfg, "https_enabled", False):
        try:
            core.start_caddy()
        except Exception as exc:
            # Mirror the port-in-use policy: with no HTTPS front-end there
            # is nothing serving the configured port, so exit loudly
            # instead of running a site nobody can reach.
            logger.error(f"HTTPS is enabled but could not be started: {exc}")
            server.stop()
            sys.exit(1)

    shutdown_event = Event()
    tray = Tray(server, on_quit=shutdown_event.set, on_start=core.start_all, on_stop=core.stop_all)

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
        core.stop_all()
        stop_transcriber()
        logger.info("RecipeServer stopped.")
