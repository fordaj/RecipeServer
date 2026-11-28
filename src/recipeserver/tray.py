import webbrowser
from pathlib import Path
import pystray
from PIL import Image

from .server import LOCALHOST, WILDCARD_BIND_ADDRESSES, Server
from ._logger import logger
from .config import DEFAULT_SERVER_PORT

FILE_PATH = Path(__file__)
LOGO_PNG = FILE_PATH.parent / "assets" / "logo.png"


class Tray:
    def __init__(self, server: Server, on_quit):
        self.server = server
        self.on_quit = on_quit
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
        port = getattr(self.server, "port", DEFAULT_SERVER_PORT)
        bind = getattr(self.server, "bind_address", LOCALHOST)
        # A wildcard bind listens on every interface, loopback included, so
        # the browser can use the loopback address. A specific non-loopback
        # bind would not answer on loopback, so open that address instead.
        if bind in WILDCARD_BIND_ADDRESSES:
            host = LOCALHOST
        elif ":" in bind:
            host = f"[{bind}]"
        else:
            host = bind
        webbrowser.open(f"http://{host}:{port}")

    def _server_status(self, item):
        return "Server: Running" if self.server.is_running else "Server: Stopped"

    def _start_server(self, icon, item):
        try:
            self.server.start()
            logger.info("Server started from tray")
        except OSError:
            logger.exception("Unable to start server from tray")

        icon.update_menu()

    def _stop_server(self, icon, item):
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
