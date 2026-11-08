import webbrowser
from pathlib import Path
import pystray
from PIL import Image, ImageDraw

from .config import DEFAULT_FOOD_COLOR
from .logo import LOGO_PNG, generate_logo_png
from .server import Server
from ._logger import logger

FILE_PATH = Path(__file__)


class Tray:
    def __init__(self, server: Server, on_quit, food_color: str | None = None):
        self.server = server
        self.on_quit = on_quit
        self.food_color = food_color or DEFAULT_FOOD_COLOR
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
        # Regenerate logo.png on app load from logo.svg using the
        # configured food color, then load it for the tray icon.
        generate_logo_png(self.food_color, LOGO_PNG)
        with Image.open(LOGO_PNG) as image:
            return image.convert("RGBA")

    def _open_recipes(self, icon, item):
        port = getattr(self.server, "port", 8000)
        webbrowser.open(f"http://localhost:{port}")

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
