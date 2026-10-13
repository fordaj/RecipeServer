import webbrowser

import pystray
from PIL import Image, ImageDraw

from .server import Server
from ._logger import logger


class Tray:
    def __init__(self, server: Server):
        self.server = server
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

    def _create_image(self):
        image = Image.new("RGB", (64, 64), "#8d5542")
        draw = ImageDraw.Draw(image)

        # Simple cookbook icon
        draw.rectangle((13, 9, 51, 55), fill="#fff8ed")
        draw.line((21, 22, 43, 22), fill="#8d5542", width=3)
        draw.line((21, 31, 43, 31), fill="#8d5542", width=3)
        draw.line((21, 40, 38, 40), fill="#8d5542", width=3)

        return image

    def _open_recipes(self, icon, item):
        webbrowser.open("http://localhost:8000")

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
        self.server.stop()
        icon.stop()

    def run(self):
        self.icon.run()
