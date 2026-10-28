from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from datetime import datetime
import json
import math
import socket
import sys
import unicodedata
import frontmatter

from .config import Configuration
from ._logger import logger
from .markdown_to_html import MarkdownToHTMLConverter

# from .metadata import RecipeMetadata
from collections.abc import Callable

RecipeConverter = Callable[[Path], tuple[Path, MarkdownToHTMLConverter]]


EDITOR_METADATA_FIELDS = {
    "tags": "string_list",
    "cuisine": "string_list",
    "category": "string_list",
    "meals": "string_list",
    "makes": "integer",
    "difficulty": "number",
}


def _validate_editor_metadata(metadata: object) -> dict:
    if not isinstance(metadata, dict):
        raise ValueError("Expected a metadata object")

    validated = {}

    for field, expected_type in EDITOR_METADATA_FIELDS.items():
        value = metadata.get(field)

        if value is None:
            validated[field] = None
        elif expected_type == "string_list":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"'{field}' must be a list of strings or null")
            validated[field] = value
        elif expected_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"'{field}' must be a string or null")
            validated[field] = value
        elif expected_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"'{field}' must be an integer or null")
            validated[field] = value
        elif expected_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"'{field}' must be a number or null")
            validated[field] = value

    return validated


def _validate_ratings(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("'ratings' must be a list")

    validated = []
    names = set()
    ids = set()

    for index, rating in enumerate(value):
        if not isinstance(rating, dict):
            raise ValueError(f"Rating {index + 1} must be an object")

        name = rating.get("name")
        rating_id = rating.get("id")
        score = rating.get("rating")

        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise ValueError(f"Rating {index + 1} must have a name of 1 to 100 characters")

        normalized_name = unicodedata.normalize("NFKC", name.strip()).casefold()
        if normalized_name in names:
            raise ValueError("There can only be one rating per name")
        names.add(normalized_name)

        if not isinstance(rating_id, str) or not rating_id.strip() or rating_id != rating_id.strip():
            raise ValueError(f"Rating {index + 1} must have an ID")
        if rating_id in ids:
            raise ValueError("Rating IDs must be unique")
        ids.add(rating_id)

        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"Rating {index + 1} must have a numeric score")
        if score < 0 or score > 10 or not math.isfinite(score):
            raise ValueError(f"Rating {index + 1} must be between 0 and 10")

        for field in ("created", "updated"):
            timestamp = rating.get(field)
            if not isinstance(timestamp, str):
                raise ValueError(f"Rating {index + 1} must have a {field} timestamp")
            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"Rating {index + 1} has an invalid {field} timestamp") from exc

        normalized_rating = rating.copy()
        normalized_rating["name"] = name.strip()
        validated.append(normalized_rating)

    return validated


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
        if parsed.path not in ("/api/markdown", "/api/recipe-editor") and not parsed.path.startswith("/api/metadata/"):
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

            # Handle metadata endpoint
            if parsed.path == "/api/metadata":
                # Read the file content and extract YAML front matter using frontmatter library
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Use frontmatter to parse the YAML front matter
                try:
                    post = frontmatter.loads(content)
                    metadata = post.metadata
                    self._send_json(200, {"metadata": metadata})
                except Exception as e:
                    logger.exception("Failed to parse YAML front matter")
                    self._send_json(500, {"error": "Unable to parse YAML front matter"})
            elif parsed.path.startswith("/api/metadata/"):
                # Handle individual metadata field endpoints
                field_name = parsed.path.split("/")[-1]

                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                try:
                    post = frontmatter.loads(content)
                    metadata = post.metadata

                    if field_name in metadata:
                        # Return the specific field value
                        self._send_json(200, {"value": metadata[field_name]})
                    elif field_name in ("comments", "ratings"):
                        self._send_json(200, {"value": []})
                    else:
                        self._send_json(404, {"error": f"Metadata field '{field_name}' not found"})
                except Exception as e:
                    logger.exception(f"Failed to parse YAML front matter for field {field_name}")
                    self._send_json(500, {"error": "Unable to parse YAML front matter"})

            elif parsed.path == "/api/recipe-editor":
                post = frontmatter.loads(file_path.read_text(encoding="utf-8"))

                metadata = {field: post.metadata.get(field) for field in EDITOR_METADATA_FIELDS}

                self._send_json(
                    200,
                    {
                        "metadata": metadata,
                        "content": post.content,
                    },
                )

            else:
                # Handle markdown endpoint - return the raw markdown content
                content = file_path.read_text(encoding="utf-8")
                self._send_bytes(200, content.encode("utf-8"), "text/markdown; charset=utf-8")

        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except OSError:
            logger.exception("Failed to read Markdown file")
            self._send_json(500, {"error": "Unable to read Markdown file"})

    def do_POST(self):
        parsed = urlsplit(self.path)

        if parsed.path not in ("/api/markdown", "/api/recipe-editor") and not parsed.path.startswith("/api/metadata/"):
            self.send_error(404, "Unknown API endpoint")
            return

        # Handle POST to /api/recipe-editor
        if parsed.path == "/api/recipe-editor":
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
                metadata = _validate_editor_metadata(payload.get("metadata"))

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

                post = frontmatter.loads(file_path.read_text(encoding="utf-8"))

                for field, value in metadata.items():
                    post.metadata[field] = value

                post.content = content
                new_content = frontmatter.dumps(post)

                file_path.write_text(new_content, encoding="utf-8", newline="")
                logger.info("Saved recipe editor content: {}", file_path)

                if self.on_markdown_saved is not None:
                    self.on_markdown_saved(file_path)

                self._send_json(200, {"success": True})

            except OSError:
                logger.exception("Failed to save recipe")
                self._send_json(500, {"error": "Unable to save recipe"})
            except Exception:
                logger.exception("Failed to save or regenerate recipe HTML")
                self._send_json(
                    500,
                    {"error": "Recipe saved, but HTML regeneration failed"},
                )

            return
        # Handle POST to individual metadata fields
        elif parsed.path.startswith("/api/metadata/") and not parsed.path == "/api/metadata":
            field_name = parsed.path.split("/")[-1]

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
                value = payload.get("value")

                if not isinstance(path, str):
                    raise ValueError("Expected string field: path")

                if field_name == "ratings":
                    value = _validate_ratings(value)

                file_path = self._resolve_markdown_path(path)

            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return

            try:
                if not file_path.is_file():
                    self._send_json(404, {"error": "Markdown file not found"})
                    return

                # Read existing content
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Parse the YAML front matter
                try:
                    post = frontmatter.loads(content)
                    metadata = post.metadata

                    # Update the specific field
                    if value is not None:
                        metadata[field_name] = value
                    else:
                        # If no value provided, remove the field
                        metadata.pop(field_name, None)

                    # Reconstruct the file with updated metadata
                    new_content = frontmatter.dumps(post)

                    # Write back to file
                    file_path.write_text(new_content, encoding="utf-8", newline="")
                    logger.info("Updated metadata field '{}' in file: {}", field_name, file_path)

                    if field_name == "ratings" and self.on_markdown_saved is not None:
                        try:
                            self.on_markdown_saved(file_path)
                        except Exception:
                            logger.exception("Ratings saved, but recipe HTML regeneration failed")
                            self._send_json(
                                500,
                                {"error": "Ratings saved, but recipe HTML regeneration failed"},
                            )
                            return

                    self._send_json(200, {"success": True, "field": field_name})

                except Exception as e:
                    logger.exception("Failed to update YAML front matter")
                    self._send_json(500, {"error": "Unable to update YAML front matter"})

            except OSError:
                logger.exception("Failed to save Markdown file")
                self._send_json(500, {"error": "Unable to save Markdown file"})
            except Exception:
                logger.exception("Failed to regenerate recipe HTML")
                self._send_json(500, {"error": "Markdown saved, but HTML regeneration failed"})
            return

        # Handle regular POST to /api/markdown (existing functionality)

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
