"""HTTP server for the generated recipe site and its editing APIs.

The request handler is intentionally split into small, focused helpers: routing
methods dispatch to endpoint handlers, endpoint handlers validate input and
coordinate I/O, and shared helpers handle payload parsing, path safety, and
metadata updates.
"""

from __future__ import annotations

import json
import math
import re
import socket
import sys
import tempfile
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timezone
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path, PureWindowsPath
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import frontmatter
from PIL import Image, UnidentifiedImageError

from . import ai_recipe
from ._logger import logger
from .archive import ARCHIVE_KINDS, archive_filename, create_archive, resolve_archive_date
from .config import Configuration
from .image_handler import IMAGE_EXTENSIONS
from .recipe_utils import is_finite_rating_score, json_default, normalize_reviewer_name

# Keep the historical module-level name for compatibility.
_json_default = json_default

MarkdownSavedCallback = Callable[[Path], None]
ConfigSavedCallback = Callable[[], None]
RecipesDeletedCallback = Callable[[list[Path]], None]

# ----- Request and server constants ----------------------------------------
# These values define request-size limits and the local server's network
# behavior. Keep them discoverable here rather than buried in handlers.

BULK_MAX_PATHS = 100
ARCHIVE_STREAM_CHUNK_BYTES = 64 * 1024

# Default port; the configured port (Configuration.server_port) wins when set.
SERVER_PORT = 8000
SERVER_BIND_ADDRESS = "0.0.0.0"
LOCALHOST = "localhost"
PUBLIC_IP_PROBE_ADDRESS = "8.8.8.8"
PUBLIC_IP_PROBE_PORT = 80


class _RequestTooLarge(ValueError):
    """Raised when a request body exceeds the accepted size."""


# ---------------------------------------------------------------------------
# Editor metadata schema and validation
# ---------------------------------------------------------------------------

EDITOR_METADATA_FIELDS = {
    "tags": "string_list",
    "cuisine": "string_list",
    "categories": "string_list",
    "meals": "string_list",
    "makes": "integer",
    "difficulty": "number",
    "contributor": "string",
    "status": "string",
    "createdOn": "string",
    "updatedOn": "string",
    "archived": "boolean",
    "source": "object",
}

# Fields a bulk edit may overwrite. ``updatedOn`` is always refreshed by the
# server, so it is never accepted as a bulk-editable field.
BULK_EDITABLE_FIELDS = tuple(field for field in EDITOR_METADATA_FIELDS if field != "updatedOn")


def _normalize_source_value(value: object) -> dict | None:
    """Coerce a source field to a single source dict or None."""
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, dict)), None)
    return value if isinstance(value, dict) else None


def _editor_metadata(metadata: dict) -> dict:
    """Return editable metadata, mapping the legacy singular category field."""
    values = {field: metadata.get(field) for field in EDITOR_METADATA_FIELDS}

    if values["categories"] is None and metadata.get("category") is not None:
        legacy = metadata["category"]
        values["categories"] = [legacy] if isinstance(legacy, str) else legacy

    # Status is a single string; older recipes may store a list.
    status = values.get("status")
    if isinstance(status, list):
        values["status"] = next((item for item in status if isinstance(item, str) and item.strip()), None)
    elif status is not None and not isinstance(status, str):
        values["status"] = None

    # The editor edits one source at a time; older recipes may store a list.
    values["source"] = _normalize_source_value(values["source"])

    # ``archived`` defaults to False when absent (or not a boolean).
    values["archived"] = metadata.get("archived") is True

    return values


def _source_is_empty(source: dict | None) -> bool:
    return not source or not any(value is not None for value in source.values())


def _recipe_folder_name(content: str, metadata: dict) -> str:
    heading = re.search(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", content, re.MULTILINE)
    title = heading.group(1) if heading else metadata.get("title")
    if not isinstance(title, str):
        title = ""

    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title)
    name = " ".join(name.split()).strip(" .")
    if not name:
        name = "New Recipe"

    encoded_name = name.encode("utf-8")[:200]
    name = encoded_name.decode("utf-8", errors="ignore").rstrip(" .") or "New Recipe"
    if re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name, re.IGNORECASE):
        name = f"_{name}"
    return name


def _apply_editor_metadata(existing: dict, values: dict) -> None:
    """Apply validated editor fields while preserving extra sources."""
    for field, value in values.items():
        if field == "source":
            _apply_source_metadata(existing, value)
        else:
            existing[field] = value


def _apply_source_metadata(existing: dict, value: dict | None) -> None:
    new_source = None if _source_is_empty(value) else value
    current = existing.get("source")

    if isinstance(current, list):
        sources = [source for source in current if isinstance(source, dict)]
        if new_source is None:
            sources = sources[1:]
        elif sources:
            sources[0] = new_source
        else:
            sources = [new_source]

        if sources:
            existing["source"] = sources
        else:
            existing.pop("source", None)
        return

    if new_source is None:
        existing.pop("source", None)
    else:
        existing["source"] = new_source


def _validate_string_list_field(field: str, value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"'{field}' must be a list of strings or null")
    return value


def _validate_string_field(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{field}' must be a string or null")
    return value


def _validate_integer_field(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{field}' must be an integer or null")
    return value


def _validate_number_field(field: str, value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{field}' must be a number or null")
    return value


def _validate_boolean_field(field: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"'{field}' must be a boolean or null")
    return value


def _validate_source_field(field: str, value: object) -> dict | None:
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, dict)), None)
        if value is None:
            return None
    if not isinstance(value, dict):
        raise ValueError(f"'{field}' must be an object or null")

    allowed_fields = {"author", "title", "format", "url"}
    return {
        key: (value.get(key).strip() or None if isinstance(value.get(key), str) else None) for key in allowed_fields
    }


def _validate_editor_field(field: str, expected_type: str, value: object) -> object:
    validators = {
        "string_list": _validate_string_list_field,
        "string": _validate_string_field,
        "integer": _validate_integer_field,
        "number": _validate_number_field,
        "boolean": _validate_boolean_field,
    }
    if expected_type in validators:
        return validators[expected_type](field, value)
    if expected_type == "object" and field == "source":
        return _validate_source_field(field, value)
    return value


def _validate_editor_metadata(metadata: object) -> dict:
    if not isinstance(metadata, dict):
        raise ValueError("Expected a metadata object")

    validated = {}
    for field, expected_type in EDITOR_METADATA_FIELDS.items():
        value = metadata.get(field)
        if value is None:
            validated[field] = None
        else:
            validated[field] = _validate_editor_field(field, expected_type, value)

    return validated


# ---------------------------------------------------------------------------
# Bulk operation validation
# ---------------------------------------------------------------------------


def _validate_bulk_paths(value: object) -> list[str]:
    """Validate the ``paths`` array shared by the bulk endpoints."""
    if not isinstance(value, list) or not value:
        raise ValueError("'paths' must be a non-empty list")
    if len(value) > BULK_MAX_PATHS:
        raise ValueError(f"'paths' must contain at most {BULK_MAX_PATHS} recipes")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError("'paths' must be a list of non-empty strings")

    unique: list[str] = []
    for item in value:
        if item not in unique:
            unique.append(item)
    return unique


def _validate_bulk_fields(value: object) -> list[str]:
    """Validate the optional ``fields`` subset for a bulk edit."""
    if value is None:
        return list(BULK_EDITABLE_FIELDS)
    if not isinstance(value, list) or not value:
        raise ValueError("'fields' must be a non-empty list")

    unknown = [field for field in value if field not in BULK_EDITABLE_FIELDS]
    if unknown:
        raise ValueError(f"Unknown bulk-editable field(s): {', '.join(map(str, unknown))}")

    return list(dict.fromkeys(value))


def _validate_bulk_rating(value: object) -> tuple[str, int | float] | None:
    """Validate a bulk rating override: add a named rating, overriding ties."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("'rating' must be an object with 'name' and 'rating'")

    name = value.get("name")
    score = value.get("rating", value.get("score"))
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError("'rating.name' must be 1 to 100 characters")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("'rating.rating' must be a number between 0 and 10")
    if score < 0 or score > 10 or not math.isfinite(score):
        raise ValueError("'rating.rating' must be between 0 and 10")
    return name.strip(), score


# ---------------------------------------------------------------------------
# Rating validation and updates
# ---------------------------------------------------------------------------


def _apply_rating_override(ratings: object, name: str, score: int | float) -> list[dict]:
    """Return ratings with the named rating added or overridden in place."""
    current = ratings if isinstance(ratings, list) else []
    updated: list[dict] = []
    replaced = False
    normalized = normalize_reviewer_name(name)
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    for item in current:
        if not isinstance(item, dict):
            continue

        existing = item.get("name")
        if isinstance(existing, str) and normalize_reviewer_name(existing) == normalized:
            updated.append({**item, "name": existing.strip(), "rating": score, "updated": now})
            replaced = True
        else:
            updated.append(item)

    if not replaced:
        updated.append({"name": name, "created": now, "updated": now, "id": str(uuid.uuid4()), "rating": score})

    return updated


def _validate_makes(value: object) -> int | None:
    """Validate a ``makes`` counter value for the per-field metadata endpoint."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("'makes' must be a non-negative integer or null")
    return value


def _validate_rating_entry(index: int, rating: object) -> tuple[str, str, dict]:
    if not isinstance(rating, dict):
        raise ValueError(f"Rating {index + 1} must be an object")

    name = rating.get("name")
    rating_id = rating.get("id")
    score = rating.get("rating")

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError(f"Rating {index + 1} must have a name of 1 to 100 characters")

    if not isinstance(rating_id, str) or not rating_id.strip() or rating_id != rating_id.strip():
        raise ValueError(f"Rating {index + 1} must have an ID")

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
    return normalize_reviewer_name(name), rating_id, normalized_rating


def _validate_ratings(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("'ratings' must be a list")

    validated = []
    names = set()
    ids = set()

    for index, rating in enumerate(value):
        normalized_name, rating_id, normalized_rating = _validate_rating_entry(index, rating)

        if normalized_name in names:
            raise ValueError("There can only be one rating per name")
        names.add(normalized_name)

        if rating_id in ids:
            raise ValueError("Rating IDs must be unique")
        ids.add(rating_id)

        validated.append(normalized_rating)

    return validated


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


class RecipeRequestHandler(SimpleHTTPRequestHandler):
    MAX_REQUEST_SIZE = 5 * 1024 * 1024
    MAX_IMAGE_UPLOAD_SIZE = 25 * 1024 * 1024
    MAX_IMAGE_UPLOAD_COUNT = 20

    def __init__(
        self,
        *args,
        source_directory: Path,
        on_markdown_saved: MarkdownSavedCallback | None = None,
        on_config_saved: ConfigSavedCallback | None = None,
        on_recipes_deleted: RecipesDeletedCallback | None = None,
        config: Configuration | None = None,
        **kwargs,
    ):
        self._source_directory = Path(source_directory).resolve()
        self.on_markdown_saved = on_markdown_saved
        self.on_config_saved = on_config_saved
        self.on_recipes_deleted = on_recipes_deleted
        self.config = config
        super().__init__(*args, **kwargs)

    @property
    def source_directory(self) -> Path:
        """Recipe source directory, following live configuration changes."""
        if self.config is not None and str(self.config.source_directory):
            return Path(self.config.source_directory).resolve()
        return self._source_directory

    # ----- routing ---------------------------------------------------------

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path

        if self._dispatch_get_api(path, parsed):
            return

        if path.startswith("/api/"):
            self.send_error(404, "Unknown API endpoint")
            return

        super().do_GET()

    def _dispatch_get_api(self, path: str, parsed) -> bool:
        simple_handlers = {
            "/health": self._handle_health,
            "/health/": self._handle_health,
            "/api/ai-status": self._handle_ai_status,
            "/api/ai-status/": self._handle_ai_status,
            "/api/config": self._handle_config_get,
            "/api/config/": self._handle_config_get,
            "/api/recipe-folders": self._handle_recipe_folders_get,
            "/api/bulk-editor": lambda: self._handle_bulk_editor_get(parsed),
            "/api/bulk-editor/": lambda: self._handle_bulk_editor_get(parsed),
        }

        if path in simple_handlers:
            simple_handlers[path]()
            return True
        if path in ("/api/archive/source", "/api/archive/site"):
            self._handle_archive(parsed)
            return True
        if path in ("/api/markdown", "/api/recipe-editor") or path.startswith("/api/metadata/"):
            self._handle_recipe_read(parsed)
            return True
        return False

    def do_POST(self):
        path = urlsplit(self.path).path

        if self._dispatch_post_api(path):
            return

        self.send_error(404, "Unknown API endpoint")

    def _dispatch_post_api(self, path: str) -> bool:
        exact_handlers = {
            "/api/bulk-editor": self._handle_bulk_editor_post,
            "/api/bulk-editor/": self._handle_bulk_editor_post,
            "/api/bulk-delete": self._handle_bulk_delete,
            "/api/bulk-delete/": self._handle_bulk_delete,
            "/api/config": self._handle_config_update,
            "/api/ai-recipe": self._handle_ai_recipe,
            "/api/find-image": self._handle_find_image,
            "/api/find-image/": self._handle_find_image,
            "/api/recipe": self._handle_recipe_create,
            "/api/recipe-editor": self._handle_recipe_editor_post,
            "/api/markdown": self._handle_markdown_post,
        }

        handler = exact_handlers.get(path)
        if handler is not None:
            handler()
            return True
        if path.startswith("/api/metadata/"):
            self._handle_metadata_post(path)
            return True
        return False

    def do_DELETE(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/api/recipe":
            self.send_error(404, "Unknown API endpoint")
            return
        self._handle_recipe_delete(parsed)

    # ----- GET handlers ----------------------------------------------------

    def _handle_health(self) -> None:
        self._send_json(200, {"status": "ok"})

    def _handle_ai_status(self) -> None:
        logger.debug("Received /api/ai-status request")
        try:
            status = ai_recipe.ai_status(self.config)
        except Exception:
            logger.exception("Failed to check local model status")
            self._send_json(500, {"error": "Unable to check local model status"})
            return

        logger.debug(f"Responding to /api/ai-status with {status}")
        self._send_json(200, status)

    def _handle_config_get(self) -> None:
        logger.debug("Received /api/config request")
        try:
            if self.config is None:
                raise ValueError("Configuration is not available")
            self._send_json(
                200,
                {
                    "values": self.config.get_config_values(),
                    "fields": self.config.field_specs(),
                },
            )
        except ValueError as exc:
            self._send_json(500, {"error": str(exc)})
        except Exception:
            logger.exception("Failed to read configuration")
            self._send_json(500, {"error": "Unable to read configuration"})

    def _handle_recipe_folders_get(self) -> None:
        try:
            self._send_json(200, {"folders": self._list_recipe_folders()})
        except OSError:
            logger.exception("Failed to list recipe folders")
            self._send_json(500, {"error": "Unable to list recipe folders"})

    def _handle_recipe_read(self, parsed) -> None:
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

            if parsed.path.startswith("/api/metadata/"):
                self._handle_metadata_get(parsed.path, file_path)
            elif parsed.path == "/api/recipe-editor":
                self._handle_recipe_editor_get(file_path)
            else:
                content = file_path.read_text(encoding="utf-8")
                self._send_bytes(200, content.encode("utf-8"), "text/markdown; charset=utf-8")
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except OSError:
            logger.exception("Failed to read Markdown file")
            self._send_json(500, {"error": "Unable to read Markdown file"})

    def _handle_metadata_get(self, path: str, file_path: Path) -> None:
        field_name = path.split("/")[-1]
        if not field_name:
            raise ValueError("Expected a metadata field name")
        if field_name == "category":
            field_name = "categories"

        try:
            recipe_post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception(f"Failed to parse YAML front matter for field {field_name}")
            self._send_json(500, {"error": "Unable to parse YAML front matter"})
            return

        metadata = recipe_post.metadata
        if field_name in metadata:
            self._send_json(200, {"value": metadata[field_name]})
        elif field_name == "categories" and "category" in metadata:
            self._send_json(200, {"value": metadata["category"]})
        elif field_name in ("comments", "ratings"):
            self._send_json(200, {"value": []})
        elif field_name == "archived":
            self._send_json(200, {"value": False})
        else:
            self._send_json(404, {"error": f"Metadata field '{field_name}' not found"})

    def _handle_recipe_editor_get(self, file_path: Path) -> None:
        try:
            recipe_post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to parse YAML front matter")
            self._send_json(500, {"error": "Unable to parse YAML front matter"})
            return

        self._send_json(
            200,
            {"metadata": _editor_metadata(recipe_post.metadata), "content": recipe_post.content},
        )

    def _handle_bulk_editor_get(self, parsed) -> None:
        try:
            raw_paths = _validate_bulk_paths(parse_qs(parsed.query).get("path", []))
            file_paths = [self._resolve_markdown_path(path) for path in raw_paths]
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        recipes = []
        try:
            for raw_path, file_path in zip(raw_paths, file_paths):
                if not file_path.is_file():
                    self._send_json(404, {"error": f"Markdown file not found: {raw_path}"})
                    return
                recipe_post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
                ratings = recipe_post.metadata.get("ratings")
                recipes.append(
                    {
                        "path": raw_path,
                        "metadata": _editor_metadata(recipe_post.metadata),
                        "ratings": ratings if isinstance(ratings, list) else [],
                    }
                )
        except Exception:
            logger.exception("Failed to read bulk editor data")
            self._send_json(500, {"error": "Unable to read recipe data"})
            return

        self._send_json(200, {"recipes": recipes})

    # ----- POST handlers: configuration and AI -----------------------------

    def _handle_config_update(self) -> None:
        try:
            payload = self._read_json_payload()
            if self.config is None:
                raise ValueError("Configuration is not available")
            changed = self.config.apply_config_values(payload.get("values"))
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except OSError:
            logger.exception("Failed to save configuration")
            self._send_json(500, {"error": "Unable to save configuration"})
            return

        logger.info(f"Saved configuration (changed: {', '.join(changed) or 'none'})")
        if self.on_config_saved is not None:
            try:
                self.on_config_saved()
            except Exception:
                logger.exception("Configuration saved, but regeneration failed")
                self._send_json(500, {"error": "Configuration saved, but regeneration failed"})
                return

        self._send_json(200, {"success": True, "values": self.config.get_config_values(), "changed": changed})

    def _handle_ai_recipe(self) -> None:
        try:
            request = self._validate_ai_recipe_request()
        except _RequestTooLarge:
            logger.warning("AI recipe request body was too large")
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning(f"Invalid AI recipe request: {exc}")
            self._send_json(400, {"error": str(exc)})
            return

        if request["stream_progress"]:
            self._stream_ai_recipe(request)
        else:
            self._run_ai_recipe(request)

    def _validate_ai_recipe_request(self) -> dict:
        payload, image = self._read_ai_recipe_payload()
        input_type = payload.get("inputType")
        input_value = payload.get("input")

        if input_type not in {"url", "text", "image"}:
            raise ValueError("Expected inputType to be 'url', 'text', or 'image'")

        if input_type == "image":
            if image is None:
                raise ValueError("Expected a recipe image upload")
            image = self._validate_uploaded_images([image])[0]
            input_value = image[0]
            logger.info(f"Received AI recipe request from image input ({image[0]}, {len(image[1])} bytes)")
        else:
            if not isinstance(input_value, str) or not input_value.strip():
                raise ValueError("Expected a non-empty input value")
            if image is not None:
                raise ValueError("Unexpected uploaded file for this inputType")
            input_value = input_value.strip()
            logger.info(f"Received AI recipe request from {input_type} input ({len(input_value)} characters)")

        return {
            "input_type": input_type,
            "input_value": input_value,
            "image": image,
            "stream_progress": payload.get("stream") is True,
        }

    def _run_ai_recipe(self, request: dict) -> None:
        try:
            result = self._generate_ai_recipe(request)
        except ai_recipe.ModelUnavailable as exc:
            logger.warning(f"Local model unavailable: {exc}")
            self._send_json(503, {"error": str(exc)})
        except (ai_recipe.ModelRequestError, ai_recipe.SourceFetchError) as exc:
            logger.warning(f"AI recipe generation failed: {exc}")
            self._send_json(502, {"error": str(exc)})
        except ValueError as exc:
            logger.warning(f"Invalid AI recipe input: {exc}")
            self._send_json(400, {"error": str(exc)})
        except Exception:
            logger.exception("Failed to generate a recipe with the local model")
            self._send_json(500, {"error": "Unable to generate recipe"})
        else:
            logger.info(f"AI recipe generation succeeded ({len(result.get('content', ''))} characters of Markdown)")
            self._send_json(200, result)

    def _stream_ai_recipe(self, request: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def send_event(event_type: str, **values) -> None:
            body = json.dumps({"type": event_type, **values}, default=_json_default).encode("utf-8")
            self.wfile.write(body + b"\n")
            self.wfile.flush()

        try:
            result = self._generate_ai_recipe(
                request, progress_callback=lambda msg: send_event("progress", message=msg)
            )
        except (ai_recipe.ModelUnavailable, ai_recipe.ModelRequestError, ai_recipe.SourceFetchError, ValueError) as exc:
            logger.warning(f"AI recipe generation failed: {exc}")
            send_event("error", message=str(exc))
        except Exception:
            logger.exception("Failed to generate a recipe with the local model")
            send_event("error", message="Unable to generate recipe")
        else:
            logger.info(f"AI recipe generation succeeded ({len(result.get('content', ''))} characters of Markdown)")
            send_event("result", result=result)

    def _handle_find_image(self) -> None:
        try:
            payload = self._read_json_payload()
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        query = payload.get("query", payload.get("search_query", payload.get("title", payload.get("recipe_title"))))
        if not isinstance(query, str) or not query.strip():
            self._send_json(400, {"error": "Type a search query before searching for an image"})
            return

        try:
            result = ai_recipe.find_image_for_recipe(self.config, query.strip())
        except ai_recipe.ModelUnavailable as exc:
            logger.warning(f"Find One for Me unavailable: {exc}")
            self._send_json(503, {"error": str(exc)})
        except ai_recipe.ImageSearchError as exc:
            logger.warning(f"Find One for Me found no suitable image: {exc}")
            self._send_json(404, {"error": str(exc)})
        except ai_recipe.ImageDownloadError as exc:
            logger.warning(f"Find One for Me download failed: {exc}")
            self._send_json(502, {"error": str(exc)})
        except (ai_recipe.ModelRequestError, ai_recipe.SourceFetchError) as exc:
            logger.warning(f"Find One for Me failed: {exc}")
            self._send_json(502, {"error": str(exc)})
        except ValueError as exc:
            logger.warning(f"Find One for Me invalid input: {exc}")
            self._send_json(400, {"error": str(exc)})
        except Exception:
            logger.exception("Failed to find an image for a recipe")
            self._send_json(500, {"error": "Unable to find an image"})
        else:
            logger.info(
                f"Found an image for query {query.strip()!r}: {result.get('filename')} "
                f"({result.get('byte_count')} bytes, source={result.get('source_url') or '(none)'})"
            )
            self._send_json(200, result)

    def _generate_ai_recipe(self, request: dict, progress_callback=None):
        if request["input_type"] == "image" and request["image"] is not None:
            filename, image_bytes = request["image"]
            return ai_recipe.generate_recipe(
                self.config,
                request["input_type"],
                filename,
                progress_callback=progress_callback,
                image_bytes=image_bytes,
                image_filename=filename,
            )
        return ai_recipe.generate_recipe(
            self.config,
            request["input_type"],
            request["input_value"],
            progress_callback=progress_callback,
        )

    # ----- POST handlers: recipe creation and editing ----------------------

    def _handle_recipe_create(self) -> None:
        try:
            payload, images = self._read_recipe_payload()
            folder = payload.get("folder")
            create_folder = payload.get("createFolder")
            content = payload.get("content")
            metadata = _validate_editor_metadata(payload.get("metadata"))

            if not isinstance(folder, str) or not isinstance(create_folder, bool):
                raise ValueError("Expected string folder and boolean createFolder fields")
            if not isinstance(content, str):
                raise ValueError("Expected string field: content")
            if "\x00" in content:
                raise ValueError("Markdown content contains a null character")
            images = self._validate_uploaded_images(images)
            folder_path = self._resolve_recipe_directory(folder)
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._create_recipe(folder_path, folder, create_folder, content, metadata, images)

    def _create_recipe(
        self, folder_path: Path, folder: str, create_folder: bool, content: str, metadata: dict, images
    ) -> None:
        try:
            folder_path = self._prepare_recipe_folder(folder_path, folder, create_folder, content, metadata)
            if folder_path is None:
                return

            file_path = folder_path / "recipe.md"
            if file_path.exists():
                self._send_json(409, {"error": "A recipe already exists in that folder"})
                return

            recipe_post = frontmatter.Post(content, **self._metadata_for_new_recipe(metadata))
            self._write_recipe_post_with_images(file_path, recipe_post, images, exclusive=True)

            logger.info(f"Created recipe: {file_path}")
            self._notify_markdown_saved(file_path)
            self._send_json(201, {"success": True, "path": file_path.relative_to(self.source_directory).as_posix()})
        except FileExistsError:
            self._send_json(409, {"error": "A recipe or folder already exists at that location"})
        except OSError:
            logger.exception("Failed to create recipe")
            self._send_json(500, {"error": "Unable to create recipe"})
        except Exception:
            logger.exception("Recipe created, but HTML regeneration failed")
            self._send_json(500, {"error": "Recipe created, but HTML regeneration failed"})

    def _prepare_recipe_folder(
        self, folder_path: Path, folder: str, create_folder: bool, content: str, metadata: dict
    ) -> Path | None:
        if not create_folder:
            if not folder_path.is_dir():
                self._send_json(404, {"error": "Recipe folder not found"})
                return None
            return folder_path

        if not folder:
            return self._create_recipe_folder(_recipe_folder_name(content, metadata))

        if folder_path.exists():
            self._send_json(409, {"error": "That folder already exists"})
            return None
        folder_path.mkdir(parents=True)
        folder_path = folder_path.resolve()
        if not folder_path.is_relative_to(self.source_directory):
            self._send_json(400, {"error": "Path must stay inside the source directory"})
            return None
        return folder_path

    @staticmethod
    def _metadata_for_new_recipe(metadata: dict) -> dict:
        recipe_metadata = {key: value for key, value in metadata.items() if value is not None}
        recipe_metadata["updatedOn"] = (
            datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
        return recipe_metadata

    def _handle_recipe_editor_post(self) -> None:
        try:
            payload, images = self._read_recipe_payload()
            path = payload.get("path")
            content = payload.get("content")
            metadata = _validate_editor_metadata(payload.get("metadata"))

            if not isinstance(path, str) or not isinstance(content, str):
                raise ValueError("Expected string fields: path and content")
            if "\x00" in content:
                raise ValueError("Markdown content contains a null character")
            images = self._validate_uploaded_images(images)
            file_path = self._resolve_markdown_path(path)
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._save_recipe_editor(file_path, content, metadata, images)

    def _save_recipe_editor(self, file_path: Path, content: str, metadata: dict, images) -> None:
        try:
            if not file_path.is_file():
                self._send_json(404, {"error": "Markdown file not found"})
                return

            recipe_post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
            _apply_editor_metadata(recipe_post.metadata, metadata)
            recipe_post.metadata.pop("category", None)
            recipe_post.metadata["updatedOn"] = (
                datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            )
            recipe_post.content = content

            self._write_recipe_post_with_images(file_path, recipe_post, images, exclusive=False)
            logger.info(f"Saved recipe editor content: {file_path}")
            self._notify_markdown_saved(file_path)
            self._send_json(200, {"success": True})
        except FileExistsError as exc:
            self._send_json(409, {"error": str(exc)})
        except OSError:
            logger.exception("Failed to save recipe")
            self._send_json(500, {"error": "Unable to save recipe"})
        except Exception:
            logger.exception("Failed to save or regenerate recipe HTML")
            self._send_json(500, {"error": "Recipe saved, but HTML regeneration failed"})

    def _write_recipe_post_with_images(self, file_path: Path, recipe_post, images, *, exclusive: bool) -> None:
        written_images = self._write_uploaded_images(file_path.parent, images)
        try:
            new_content = frontmatter.dumps(recipe_post)
            if exclusive:
                with file_path.open("x", encoding="utf-8", newline="") as recipe_file:
                    recipe_file.write(new_content)
            else:
                file_path.write_text(new_content, encoding="utf-8", newline="")
        except Exception:
            self._remove_uploaded_images(written_images)
            raise

    def _handle_metadata_post(self, path: str) -> None:
        field_name = path.split("/")[-1]
        if not field_name:
            self._send_json(400, {"error": "Expected a metadata field name"})
            return
        if field_name == "category":
            field_name = "categories"

        try:
            payload = self._read_json_payload()
            recipe_path = payload.get("path")
            value = payload.get("value")
            if not isinstance(recipe_path, str):
                raise ValueError("Expected string field: path")

            if field_name == "ratings":
                value = _validate_ratings(value)
            elif field_name == "makes":
                value = _validate_makes(value)
            elif field_name == "archived":
                if value is not None:
                    value = _validate_boolean_field(field_name, value)
            elif field_name == "status":
                if value is not None:
                    value = _validate_string_field(field_name, value)

            file_path = self._resolve_markdown_path(recipe_path)
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._save_metadata_field(file_path, field_name, value)

    def _save_metadata_field(self, file_path: Path, field_name: str, value) -> None:
        try:
            if not file_path.is_file():
                self._send_json(404, {"error": "Markdown file not found"})
                return

            recipe_post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
            metadata = recipe_post.metadata
            if value is not None:
                metadata[field_name] = value
            else:
                metadata.pop(field_name, None)
            if field_name == "categories":
                metadata.pop("category", None)

            file_path.write_text(frontmatter.dumps(recipe_post), encoding="utf-8", newline="")
            logger.info(f"Updated metadata field '{field_name}' in file: {file_path}")

            if self.on_markdown_saved is not None:
                try:
                    self.on_markdown_saved(file_path)
                except Exception:
                    logger.exception("Metadata saved, but recipe regeneration failed")
                    self._send_json(500, {"error": "Metadata saved, but recipe regeneration failed"})
                    return

            self._send_json(200, {"success": True, "field": field_name})
        except OSError:
            logger.exception("Failed to save Markdown file")
            self._send_json(500, {"error": "Unable to save Markdown file"})
        except Exception:
            logger.exception("Failed to update YAML front matter")
            self._send_json(500, {"error": "Unable to update YAML front matter"})

    def _handle_markdown_post(self) -> None:
        try:
            payload = self._read_json_payload()
            path = payload.get("path")
            content = payload.get("content")
            if not isinstance(path, str) or not isinstance(content, str):
                raise ValueError("Expected string fields: path and content")
            if "\x00" in content:
                raise ValueError("Markdown content contains a null character")
            file_path = self._resolve_markdown_path(path)
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        try:
            if not file_path.is_file():
                self._send_json(404, {"error": "Markdown file not found"})
                return

            file_path.write_text(content, encoding="utf-8", newline="")
            logger.info(f"Saved Markdown file: {file_path}")
            self._notify_markdown_saved(file_path)
            self._send_json(200, {"success": True})
        except OSError:
            logger.exception("Failed to save Markdown file")
            self._send_json(500, {"error": "Unable to save Markdown file"})
        except Exception:
            logger.exception("Failed to regenerate recipe HTML")
            self._send_json(500, {"error": "Markdown saved, but HTML regeneration failed"})

    def _notify_markdown_saved(self, file_path: Path) -> None:
        if self.on_markdown_saved is not None:
            self.on_markdown_saved(file_path)

    # ----- POST handlers: bulk operations ----------------------------------

    def _handle_bulk_editor_post(self) -> None:
        try:
            payload = self._read_json_payload()
            raw_paths = _validate_bulk_paths(payload.get("paths"))
            fields = _validate_bulk_fields(payload.get("fields"))
            metadata = _validate_editor_metadata(payload.get("metadata")) if payload.get("metadata") is not None else {}
            rating_override = _validate_bulk_rating(payload.get("rating"))
            if not metadata and rating_override is None:
                raise ValueError("Expected 'metadata' and/or 'rating'")
            file_paths = [self._resolve_markdown_path(path) for path in raw_paths]
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        # Pre-check every target before writing any of them.
        for raw_path, file_path in zip(raw_paths, file_paths):
            if not file_path.is_file():
                self._send_json(404, {"error": f"Markdown file not found: {raw_path}"})
                return

        try:
            saved = self._apply_bulk_edit(file_paths, fields, metadata, rating_override)
        except OSError:
            logger.exception("Failed to save bulk edit")
            self._send_json(500, {"error": "Unable to save recipes"})
            return
        except Exception:
            logger.exception("Failed to parse recipe for bulk edit")
            self._send_json(500, {"error": "Unable to parse recipe data"})
            return

        if self.on_markdown_saved is not None:
            try:
                for file_path in saved:
                    self.on_markdown_saved(file_path)
            except Exception:
                logger.exception("Bulk edit saved, but HTML regeneration failed")
                self._send_json(500, {"error": "Recipes saved, but HTML regeneration failed"})
                return

        self._send_json(200, {"success": True, "paths": raw_paths, "count": len(raw_paths)})

    @staticmethod
    def _apply_bulk_edit(file_paths: list[Path], fields: list[str], metadata: dict, rating_override) -> list[Path]:
        saved: list[Path] = []
        for file_path in file_paths:
            recipe_post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
            if metadata:
                subset = {field: metadata.get(field) for field in fields}
                _apply_editor_metadata(recipe_post.metadata, subset)
                recipe_post.metadata.pop("category", None)
            if rating_override is not None:
                name, score = rating_override
                recipe_post.metadata["ratings"] = _apply_rating_override(
                    recipe_post.metadata.get("ratings"), name, score
                )
            if metadata or rating_override is not None:
                recipe_post.metadata["updatedOn"] = (
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                )

            file_path.write_text(frontmatter.dumps(recipe_post), encoding="utf-8", newline="")
            saved.append(file_path)
            logger.info(f"Bulk-saved recipe: {file_path}")
        return saved

    def _handle_bulk_delete(self) -> None:
        try:
            payload = self._read_json_payload()
            raw_paths = _validate_bulk_paths(payload.get("paths"))
            file_paths = [self._resolve_markdown_path(path) for path in raw_paths]
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        for raw_path, file_path in zip(raw_paths, file_paths):
            if not file_path.is_file():
                self._send_json(404, {"error": f"Markdown file not found: {raw_path}"})
                return

        try:
            deleted = self._delete_recipe_files(file_paths)
        except OSError:
            logger.exception("Failed to bulk-delete recipes")
            self._send_json(500, {"error": "Unable to delete recipes"})
            return

        if self.on_recipes_deleted is not None:
            try:
                self.on_recipes_deleted(deleted)
            except Exception:
                logger.exception("Recipes deleted, but index regeneration failed")
                self._send_json(500, {"error": "Recipes deleted, but index regeneration failed"})
                return

        self._send_json(200, {"success": True, "paths": raw_paths, "count": len(raw_paths)})

    def _delete_recipe_files(self, file_paths: list[Path]) -> list[Path]:
        deleted: list[Path] = []
        for file_path in file_paths:
            file_path.unlink()
            deleted.append(file_path)
            recipe_dir = file_path.parent
            if recipe_dir != self.source_directory and not any(recipe_dir.iterdir()):
                recipe_dir.rmdir()
            logger.info(f"Bulk-deleted recipe: {file_path}")
        return deleted

    # ----- DELETE handlers -------------------------------------------------

    def _handle_recipe_delete(self, parsed) -> None:
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

            recipe_dir = file_path.parent
            file_path.unlink()
            if recipe_dir != self.source_directory and not any(recipe_dir.iterdir()):
                recipe_dir.rmdir()
        except OSError:
            logger.exception("Failed to delete recipe")
            self._send_json(500, {"error": "Unable to delete recipe"})
            return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except Exception:
            logger.exception("Failed to delete recipe")
            self._send_json(500, {"error": "Unable to delete recipe"})
            return

        logger.info(f"Deleted recipe: {file_path}")
        if self.on_recipes_deleted is not None:
            try:
                self.on_recipes_deleted([file_path])
            except Exception:
                logger.exception("Recipe deleted, but index regeneration failed")
                self._send_json(500, {"error": "Recipe deleted, but index regeneration failed"})
                return
        self._send_json(200, {"success": True})

    # ----- archive handling ------------------------------------------------

    def _handle_archive(self, parsed) -> None:
        kind = parsed.path.rsplit("/", 1)[-1]
        if kind not in ARCHIVE_KINDS:
            self.send_error(404, "Unknown archive kind")
            return

        try:
            dates = parse_qs(parsed.query).get("date", [])
            if len(dates) > 1:
                raise ValueError("Expected a single date parameter")
            archive_date = resolve_archive_date(dates[0] if dates else None)
            filename = archive_filename(kind, archive_date)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        directory = self.source_directory if kind == "source" else Path(self.directory).resolve()
        if not directory.is_dir():
            self._send_json(404, {"error": "Archive directory not found"})
            return

        self._stream_archive(kind, directory, filename)

    def _stream_archive(self, kind: str, directory: Path, filename: str) -> None:
        archive_path = Path()
        headers_sent = False
        try:
            with tempfile.NamedTemporaryFile(prefix="recipeserver-", suffix=".7z", delete=False) as temp:
                archive_path = Path(temp.name)

            create_archive(directory, archive_path)
            size = archive_path.stat().st_size

            self.send_response(200)
            self.send_header("Content-Type", "application/x-7z-compressed")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            headers_sent = True

            with archive_path.open("rb") as archive_file:
                while chunk := archive_file.read(ARCHIVE_STREAM_CHUNK_BYTES):
                    self.wfile.write(chunk)
            logger.info(f"Downloaded archive: {kind} as {filename} ({size} bytes)")
        except BrokenPipeError:
            logger.debug(f"Archive download interrupted: {kind} as {filename}")
        except Exception:
            logger.exception(f"Failed to build {kind} archive")
            if not headers_sent:
                self._send_json(500, {"error": "Unable to build archive"})
        finally:
            if archive_path != Path():
                archive_path.unlink(missing_ok=True)

    # ----- request payload parsing -----------------------------------------

    def _read_body(self, max_size: int, too_large_message: str) -> bytes:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("Missing Content-Length")

        try:
            length = int(content_length)
        except ValueError:
            raise ValueError("Invalid Content-Length") from None

        if length < 0:
            raise ValueError("Invalid Content-Length")
        if length > max_size:
            raise _RequestTooLarge(too_large_message)

        return self.rfile.read(length)

    def _read_json_payload(self) -> dict:
        body = self._read_body(self.MAX_REQUEST_SIZE, "Request body too large")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc.msg}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        return payload

    def _parse_multipart_message(self, body: bytes, content_type: str) -> Message:
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        if not message.is_multipart():
            raise ValueError("Invalid multipart request")
        return message

    def _read_ai_recipe_payload(self) -> tuple[dict, tuple[str, bytes] | None]:
        """Read an AI recipe request, which may carry a multipart image upload."""
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            return self._read_json_payload(), None

        body = self._read_body(self.MAX_IMAGE_UPLOAD_SIZE, "Image upload request too large")
        message = self._parse_multipart_message(body, content_type)

        payload: dict = {}
        image: tuple[str, bytes] | None = None
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not isinstance(field_name, str):
                raise ValueError("Invalid multipart field")

            filename = part.get_filename()
            content = part.get_payload(decode=True) or b""
            if filename is not None:
                if field_name != "image":
                    raise ValueError("Unexpected uploaded file field")
                if image is not None:
                    raise ValueError("Expected a single recipe image upload")
                image = (filename, content)
                continue

            try:
                payload[field_name] = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Invalid text field: {field_name}") from exc

        if "stream" in payload:
            if payload["stream"] not in {"true", "false"}:
                raise ValueError("Invalid stream value")
            payload["stream"] = payload["stream"] == "true"

        return payload, image

    def _read_recipe_payload(self) -> tuple[dict, list[tuple[str, bytes]]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            return self._read_json_payload(), []

        body = self._read_body(self.MAX_IMAGE_UPLOAD_SIZE, "Image upload request too large")
        message = self._parse_multipart_message(body, content_type)

        payload = {}
        images = []
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not isinstance(field_name, str):
                raise ValueError("Invalid multipart field")

            filename = part.get_filename()
            content = part.get_payload(decode=True) or b""
            if filename is not None:
                if field_name != "images":
                    raise ValueError("Unexpected uploaded file field")
                images.append((filename, content))
                continue

            try:
                payload[field_name] = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Invalid text field: {field_name}") from exc

        if "metadata" in payload:
            try:
                payload["metadata"] = json.loads(payload["metadata"])
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid metadata JSON") from exc
        if "createFolder" in payload:
            if payload["createFolder"] not in {"true", "false"}:
                raise ValueError("Invalid createFolder value")
            payload["createFolder"] = payload["createFolder"] == "true"

        return payload, images

    # ----- image upload validation -----------------------------------------

    def _validate_uploaded_images(self, images: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
        if len(images) > self.MAX_IMAGE_UPLOAD_COUNT:
            raise ValueError(f"Upload no more than {self.MAX_IMAGE_UPLOAD_COUNT} images at a time")

        validated = []
        names = set()
        total_size = 0
        for filename, content in images:
            self._validate_image_filename(filename)
            if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
                raise ValueError(f"Unsupported image type: {filename}")
            if not content:
                raise ValueError(f"Image is empty: {filename}")
            self._validate_image_content(filename, content)

            normalized_name = filename.casefold()
            if normalized_name in names:
                raise ValueError(f"Duplicate image filename: {filename}")
            names.add(normalized_name)
            total_size += len(content)
            if total_size > self.MAX_IMAGE_UPLOAD_SIZE:
                raise _RequestTooLarge("Image upload request too large")
            validated.append((filename, content))

        return validated

    @staticmethod
    def _validate_image_filename(filename: str) -> None:
        windows_path = PureWindowsPath(filename)
        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or windows_path.name != filename
            or any(ord(character) < 32 or character in '<>:"|?*' for character in filename)
            or filename.endswith((".", " "))
        ):
            raise ValueError("Invalid image filename")

        reserved_names = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        if PureWindowsPath(filename.split(".", 1)[0]).name.upper() in reserved_names:
            raise ValueError("Invalid image filename")

    @staticmethod
    def _validate_image_content(filename: str, content: bytes) -> None:
        extension = Path(filename).suffix.lower()
        if extension == ".svg":
            RecipeRequestHandler._validate_svg_content(filename, content)
            return

        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError(f"Invalid image file: {filename}") from exc

    @staticmethod
    def _validate_svg_content(filename: str, content: bytes) -> None:
        if b"<!doctype" in content.lower():
            raise ValueError(f"Invalid SVG image: {filename}")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid SVG image: {filename}") from exc
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            raise ValueError(f"Invalid SVG image: {filename}")

        blocked_tags = {"script", "foreignobject"}
        for element in root.iter():
            tag_name = element.tag.rsplit("}", 1)[-1].lower()
            if tag_name in blocked_tags:
                raise ValueError(f"SVG contains unsupported active content: {filename}")
            for attribute, value in element.attrib.items():
                attr_name = attribute.rsplit("}", 1)[-1].lower()
                if attr_name.startswith("on"):
                    raise ValueError(f"SVG contains unsupported active content: {filename}")
                if attr_name in {"href", "style"} and (
                    ("url(" in value.lower() and "url(#" not in value.lower())
                    or (attribute.lower().endswith("href") and not value.startswith("#"))
                ):
                    raise ValueError(f"SVG contains unsupported external content: {filename}")

    @staticmethod
    def _write_uploaded_images(directory: Path, images: list[tuple[str, bytes]]) -> list[Path]:
        existing_names = {entry.name.casefold() for entry in directory.iterdir()}
        for filename, _ in images:
            if filename.casefold() in existing_names:
                raise FileExistsError(f"An item named {filename} already exists in the recipe folder")

        written = []
        try:
            for filename, content in images:
                image_path = directory / filename
                with image_path.open("xb") as image_file:
                    written.append(image_path)
                    image_file.write(content)
        except Exception:
            RecipeRequestHandler._remove_uploaded_images(written)
            raise
        return written

    @staticmethod
    def _remove_uploaded_images(images: list[Path]) -> None:
        for image in images:
            image.unlink(missing_ok=True)

    # ----- path safety and folder helpers ----------------------------------

    def _resolve_markdown_path(self, requested_path: str) -> Path:
        if not requested_path or "\\" in requested_path or "\x00" in requested_path:
            raise ValueError("Invalid file path")

        relative_path = Path(requested_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Path must stay inside the source directory")
        if relative_path.suffix.lower() != ".md":
            raise ValueError("Only Markdown (.md) files can be edited")

        root = self.source_directory
        file_path = (root / relative_path).resolve()
        if not file_path.is_relative_to(root):
            raise ValueError("Path must stay inside the source directory")
        return file_path

    def _resolve_recipe_directory(self, requested_path: str) -> Path:
        if "\\" in requested_path or "\x00" in requested_path:
            raise ValueError("Invalid folder path")
        if requested_path and (
            requested_path.startswith("/") or any(part in {"", ".", ".."} for part in requested_path.split("/"))
        ):
            raise ValueError("Folder path must stay inside the source directory")

        relative_path = Path(requested_path) if requested_path else Path()
        if relative_path.is_absolute() or relative_path.drive or ".." in relative_path.parts:
            raise ValueError("Folder path must stay inside the source directory")

        folder_path = (self.source_directory / relative_path).resolve()
        if not folder_path.is_relative_to(self.source_directory):
            raise ValueError("Folder path must stay inside the source directory")
        return folder_path

    def _create_recipe_folder(self, name: str) -> Path:
        suffix = 0
        while True:
            folder_name = name if suffix == 0 else f"{name} ({suffix})"
            folder_path = self.source_directory / folder_name
            try:
                folder_path.mkdir()
                return folder_path
            except FileExistsError:
                suffix += 1

    def _list_recipe_folders(self) -> list[str]:
        folders = []
        if not (self.source_directory / "recipe.md").exists():
            folders.append("")

        for folder in self.source_directory.rglob("*"):
            if folder.is_symlink() or not folder.is_dir():
                continue
            resolved_folder = folder.resolve()
            if not resolved_folder.is_relative_to(self.source_directory) or (resolved_folder / "recipe.md").exists():
                continue
            folders.append(folder.relative_to(self.source_directory).as_posix())

        return sorted(folders, key=str.casefold)

    # ----- response helpers ------------------------------------------------

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, default=_json_default).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


class Server:
    def __init__(
        self,
        cfg: Configuration,
        on_markdown_saved: MarkdownSavedCallback | None = None,
        on_config_saved: ConfigSavedCallback | None = None,
        on_recipes_deleted: RecipesDeletedCallback | None = None,
    ):
        self.cfg = cfg
        self.on_markdown_saved = on_markdown_saved
        self.on_config_saved = on_config_saved
        self.on_recipes_deleted = on_recipes_deleted
        self._http_server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        """Configured listen port, falling back to the default."""
        configured = getattr(self.cfg, "server_port", None)
        return configured if isinstance(configured, int) and 1 <= configured <= 65535 else SERVER_PORT

    def _port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex((LOCALHOST, port)) == 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running:
            return

        if self._port_in_use(SERVER_PORT):
            logger.error(f"Port {self.port} in use!")
            sys.exit(1)

        handler = partial(
            RecipeRequestHandler,
            directory=str(self.cfg.site_directory),
            source_directory=self.cfg.source_directory,
            on_markdown_saved=self.on_markdown_saved,
            on_config_saved=self.on_config_saved,
            on_recipes_deleted=self.on_recipes_deleted,
            config=self.cfg,
        )

        try:
            http_server = ThreadingHTTPServer((SERVER_BIND_ADDRESS, self.port), handler)
        except OSError:
            logger.exception(f"Failed to start server on port {self.port}")
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
                sock.connect((PUBLIC_IP_PROBE_ADDRESS, PUBLIC_IP_PROBE_PORT))
                ip_address = sock.getsockname()[0]
            except OSError:
                ip_address = "unavailable"

        logger.info(f"Server started on port {self.port}")
        logger.info(f"Hostname: http://{socket.gethostname()}.local:{self.port}")
        logger.info(f"IP: http://{ip_address}:{self.port}")

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
