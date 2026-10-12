from .config import Configuration
from ._logger import logger
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket


class Server:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg

    def _port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex(("localhost", port)) == 0

    def run(self):
        handler = partial(SimpleHTTPRequestHandler, directory=self.cfg.working_directory)

        if self._port_in_use(8000):
            logger.error("Port 8000 is already in use")
        else:
            server = ThreadingHTTPServer(("0.0.0.0", 8000), handler)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                ip_address = sock.getsockname()[0]
            print(f"Hostname: http://{socket.gethostname()}.local:8000")
            print(f"IP:       http://{ip_address}:8000")
            server.serve_forever()
