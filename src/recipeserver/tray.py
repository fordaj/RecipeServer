import webbrowser
from collections.abc import Callable
from pathlib import Path
import pystray
from PIL import Image, ImageDraw

from .server import Server
from ._logger import logger

FILE_PATH = Path(__file__)
LOGO_PNG = FILE_PATH.parent / "assets" / "logo.png"


class Tray:
    def __init__(self, server: Server, on_quit, on_start: Callable[[], None] | None = None, on_stop: Callable[[], None] | None = None):
        self.server = server
        self.on_quit = on_quit
        # Optional hooks that start/stop the whole site (the embedded
        # server plus Caddy when HTTPS is enabled). Without them the tray
        # drives the embedded server directly, which is all plain HTTP
        # needs.
        self._on_start = on_start
        self._on_stop = on_stop
        self.icon = pystray.Icon(
            "RecipeServer",
            self._create_image(),
            "RecipeServer",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Open Recipes",
                    self._open_recipes,
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    self._server_status,
                    None,
                    enabled=False,
                ),
                pystray.MenuItem(
                    "Start Server",
                    self._start_server,
                    visible=lambda item: not self.server.is_running,
                ),
                pystray.MenuItem(
                    "Stop Server",
                    self._stop_server,
                    visible=lambda item: self.server.is_running,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )

    def _create_image(self) -> Image.Image:
        with Image.open(LOGO_PNG) as image:
            return image.convert("RGBA")

    def _open_recipes(self, icon, item):
        port = getattr(self.server, "port", 8000)
        scheme = getattr(self.server, "scheme", "http")
        # 127.0.0.1 instead of "localhost": the server listens on the IPv4
        # loopback address only, and "localhost" may resolve to IPv6 first.
        webbrowser.open(f"{scheme}://127.0.0.1:{port}")

    def _server_status(self, item):
        return "Server: Running" if self.server.is_running else "Server: Stopped"

    def _start_server(self, icon, item):
        try:
            if self._on_start is not None:
                self._on_start()
            else:
                self.server.start()
            logger.info("Server started from tray")
        except Exception:
            # Includes OSError from the listener and failures to re-enable
            # HTTPS (for example Caddy failing to bind the public port).
            logger.exception("Unable to start server from tray")

        icon.update_menu()

    def _stop_server(self, icon, item):
        if self._on_stop is not None:
            self._on_stop()
        else:
            self.server.stop()
        logger.info("Server stopped from tray")
        icon.update_menu()

    def _quit(self, icon, item):
        self.on_quit()

    def run(self):
        self.icon.run()

    def stop(self):
        self.icon.stop()

    def run_detached(self):
        self.icon.run_detached()
