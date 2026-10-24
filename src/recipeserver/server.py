from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
import json
import socket
import sys

from .config import Configuration
from ._logger import logger
from .markdown_to_html import MarkdownToHTMLConverter
from collections.abc import Callable

RecipeConverter = Callable[[Path], tuple[Path, MarkdownToHTMLConverter]]


class RecipeRequestHandler(SimpleHTTPRequestHandler):
    MAX_REQUEST_SIZE = 5 * 1024 * 1024

    def __init__(
        self,
        *args,
        source_directory: Path,
        on_markdown_saved: RecipeConverter | None = None,
        **kwargs,
    ):
        self.source_directory = Path(source_directory).resolve()
        self.on_markdown_saved = on_markdown_saved
        super().__init__(*args, **kwargs)

    def do_GET(self):
        parsed = urlsplit(self.path)

        if parsed.path != "/api/markdown":
            if parsed.path.startswith("/api/"):
                self.send_error(404, "Unknown API endpoint")
                return

            super().do_GET()
            return

        query = parse_qs(parsed.query)
        paths = query.get("path", [])

        if len(paths) != 1 or not paths[0]:
            self._send_json(400, {"error": "Expected a path parameter"})
            return

        try:
            file_path = self._resolve_markdown_path(paths[0])

            if not file_path.is_file():
                self._send_json(404, {"error": "Markdown file not found"})
                return

            content = file_path.read_text(encoding="utf-8")
            self._send_bytes(200, content.encode("utf-8"), "text/markdown; charset=utf-8")

        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except OSError:
            logger.exception("Failed to read Markdown file")
            self._send_json(500, {"error": "Unable to read Markdown file"})

    def do_POST(self):
        if urlsplit(self.path).path != "/api/markdown":
            self.send_error(404, "Unknown API endpoint")
            return

        content_length = self.headers.get("Content-Length")

        try:
            if content_length is None:
                raise ValueError("Missing Content-Length")

            length = int(content_length)

            if length < 0:
                raise ValueError("Invalid Content-Length")

            if length > self.MAX_REQUEST_SIZE:
                self._send_json(413, {"error": "Request body too large"})
                return

            body = self.rfile.read(length)
            payload = json.loads(body)

            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")

            path = payload.get("path")
            content = payload.get("content")

            if not isinstance(path, str) or not isinstance(content, str):
                raise ValueError("Expected string fields: path and content")

            if "\x00" in content:
                raise ValueError("Markdown content contains a null character")

            file_path = self._resolve_markdown_path(path)

        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        try:
            if not file_path.is_file():
                self._send_json(404, {"error": "Markdown file not found"})
                return

            file_path.write_text(content, encoding="utf-8", newline="")
            logger.info("Saved Markdown file: {}", file_path)

            if self.on_markdown_saved is not None:
                self.on_markdown_saved(file_path)

            self._send_json(200, {"success": True})

        except OSError:
            logger.exception("Failed to save Markdown file")
            self._send_json(500, {"error": "Unable to save Markdown file"})
        except Exception:
            logger.exception("Failed to regenerate recipe HTML")
            self._send_json(500, {"error": "Markdown saved, but HTML regeneration failed"})

    def _resolve_markdown_path(self, requested_path: str) -> Path:
        # Require a relative, forward-slash-separated path.
        if not requested_path or "\\" in requested_path or "\x00" in requested_path:
            raise ValueError("Invalid file path")

        relative_path = Path(requested_path)

        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Path must stay inside the source directory")

        if relative_path.suffix.lower() != ".md":
            raise ValueError("Only Markdown (.md) files can be edited")

        root = self.source_directory
        file_path = (root / relative_path).resolve()

        # Block symlinks that point outside the source directory.
        if not file_path.is_relative_to(root):
            raise ValueError("Path must stay inside the source directory")

        return file_path

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class Server:
    def __init__(
        self,
        cfg: Configuration,
        on_markdown_saved: RecipeConverter | None = None,
    ):
        self.cfg = cfg
        self.on_markdown_saved = on_markdown_saved
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
            RecipeRequestHandler,
            directory=str(self.cfg.site_directory),
            source_directory=self.cfg.source_directory,
            on_markdown_saved=self.on_markdown_saved,
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
