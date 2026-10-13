from .config import Configuration
from ._logger import logger
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import socket, sys


class Server:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self._http_server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def _port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex(("localhost", port)) == 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running:
            return

        if self._port_in_use(8000):
            logger.error("Port 8000 in use!")
            sys.exit(1)

        handler = partial(
            SimpleHTTPRequestHandler,
            directory=str(self.cfg.working_directory),
        )

        try:
            http_server = ThreadingHTTPServer(("0.0.0.0", 8000), handler)
        except OSError:
            logger.exception("Failed to start server on port 8000")
            raise

        self._http_server = http_server
        self._thread = Thread(
            target=http_server.serve_forever,
            name="RecipeServer",
            daemon=True,
        )
        self._thread.start()

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.connect(("8.8.8.8", 80))
                ip_address = sock.getsockname()[0]
            except OSError:
                ip_address = "unavailable"

        logger.info("Server started on port 8000")
        logger.info(f"Hostname: http://{socket.gethostname()}.local:8000")
        logger.info("IP: http://{}:8000", ip_address)

    def stop(self):
        if self._http_server is None:
            return

        http_server = self._http_server
        thread = self._thread

        self._http_server = None
        self._thread = None

        http_server.shutdown()
        http_server.server_close()

        if thread is not None:
            thread.join()

        logger.info("Server stopped")
