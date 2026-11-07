from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from datetime import date, datetime, timezone
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
import json
import math
import re
import socket
import sys
import tempfile
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import frontmatter
from pathlib import PureWindowsPath
from PIL import Image, UnidentifiedImageError

from .image_handler import IMAGE_EXTENSIONS

from . import ai_recipe
from .archive import ARCHIVE_KINDS, archive_filename, create_archive, resolve_archive_date
from .config import Configuration
from ._logger import logger

from collections.abc import Callable

MarkdownSavedCallback = Callable[[Path], None]
RecipesSavedCallback = Callable[[list[Path]], None]
ConfigSavedCallback = Callable[[], None]


def _json_default(value: object) -> str:
    """Serialize YAML dates that JSON does not understand."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class _RequestTooLarge(ValueError):
    pass


EDITOR_METADATA_FIELDS = {
    "tags": "string_list",
    "cuisine": "string_list",
    "categories": "string_list",
    "meals": "string_list",
    "makes": "integer",
    "difficulty": "number",
    "contributor": "string",
    "createdOn": "string",
    "updatedOn": "string",
    "source": "object",
}


def _editor_metadata(metadata: dict) -> dict:
    """Return editable metadata, mapping the legacy singular category field."""
    values = {field: metadata.get(field) for field in EDITOR_METADATA_FIELDS}

    if values["categories"] is None and metadata.get("category") is not None:
        legacy = metadata["category"]
        values["categories"] = [legacy] if isinstance(legacy, str) else legacy

    # The editor edits one source at a time; older recipes may store a list.
    source = values["source"]
    if isinstance(source, list):
        values["source"] = next((item for item in source if isinstance(item, dict)), None)
    elif not isinstance(source, dict):
        values["source"] = None

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
        if field != "source":
            existing[field] = value
            continue

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
        elif new_source is None:
            existing.pop("source", None)
        else:
            existing["source"] = new_source


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
        elif expected_type == "object" and field == "source":
            if isinstance(value, list):
                value = next((item for item in value if isinstance(item, dict)), None)
                if value is None:
                    validated[field] = None
                    continue
            if not isinstance(value, dict):
                raise ValueError(f"'{field}' must be an object or null")

            allowed_fields = {"author", "title", "format", "url"}

            validated[field] = {
                key: (value.get(key).strip() or None if isinstance(value.get(key), str) else None)
                for key in allowed_fields
            }

    return validated


# Fields the bulk editor is allowed to touch. Everything else (makes, difficulty,
# updatedOn, ratings via the metadata endpoint) is intentionally excluded.
BULK_METADATA_TYPES = {
    "tags": "string_list",
    "cuisine": "string_list",
    "categories": "string_list",
    "meals": "string_list",
    "contributor": "string",
    "createdOn": "string",
    "source": "source_patch",
}

_SOURCE_PATCH_FIELDS = {"author", "title", "format", "url"}


def _validate_source_patch(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("'source' must be an object")

    patch: dict[str, str | None] = {}
    for key, sub in value.items():
        if key not in _SOURCE_PATCH_FIELDS:
            raise ValueError(f"Unknown source field '{key}'")
        if sub is None:
            patch[key] = None
            continue
        if not isinstance(sub, str):
            raise ValueError(f"'source.{key}' must be a string or null")
        patch[key] = sub.strip() or None

    return patch


def _validate_bulk_metadata(metadata: object) -> dict:
    """Validate the partial metadata patch used by the bulk editor.

    Only the fields present in ``metadata`` are touched; a value of ``null``
    clears that field on every selected recipe.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Expected a metadata object")

    validated: dict[str, object] = {}

    for field, value in metadata.items():
        expected_type = BULK_METADATA_TYPES.get(field)
        if expected_type is None:
            raise ValueError(f"'{field}' cannot be bulk edited")

        if field == "source":
            validated[field] = _validate_source_patch(value)
            continue

        if value is None:
            validated[field] = None
            continue

        if expected_type == "string_list":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"'{field}' must be a list of strings or null")
            validated[field] = [item.strip() for item in value if item.strip()]
        elif expected_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"'{field}' must be a string or null")
            validated[field] = value

    return validated


def _validate_bulk_rating(value: object) -> dict | None:
    """Validate the single rating applied to every selected recipe."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("'rating' must be an object")

    name = value.get("name")
    score = value.get("rating")

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError("'rating.name' must be 1 to 100 characters")

    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or score < 0
        or score > 10
    ):
        raise ValueError("'rating.rating' must be a number between 0 and 10")

    return {"name": name.strip(), "rating": score}


def _source_has_values(source: object) -> bool:
    if not isinstance(source, dict):
        return False
    return any(isinstance(value, str) and value.strip() for value in source.values())


def _apply_source_patch(metadata: dict, patch: dict) -> None:
    """Merge a per-field source patch into the stored source value."""
    current = metadata.get("source")

    if isinstance(current, list):
        sources = [source for source in current if isinstance(source, dict)]
        base = dict(sources[0]) if sources else {}
        rest = sources[1:]
        as_list = True
    elif isinstance(current, dict):
        base = dict(current)
        rest = []
        as_list = False
    else:
        base = {}
        rest = []
        as_list = False

    for key, value in patch.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value

    if _source_has_values(base):
        metadata["source"] = [base, *rest] if as_list or rest else base
    elif rest:
        metadata["source"] = rest
    else:
        metadata.pop("source", None)


def _apply_bulk_metadata(metadata: dict, patch: dict) -> None:
    """Apply a validated bulk metadata patch in place."""
    for field, value in patch.items():
        if field == "source":
            _apply_source_patch(metadata, value)
            continue

        if value is None:
            metadata.pop(field, None)
        else:
            metadata[field] = value

        if field == "categories":
            metadata.pop("category", None)


def _apply_bulk_rating(metadata: dict, rating: dict) -> None:
    """Add or override the rating under ``rating['name']`` in place."""
    ratings = metadata.get("ratings")
    if not isinstance(ratings, list):
        ratings = []

    name = rating["name"]
    normalized = unicodedata.normalize("NFKC", name.strip()).casefold()
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    created = now
    rating_id = str(uuid.uuid4())
    kept: list = []

    for entry in ratings:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue

        entry_name = entry.get("name")
        if (
            isinstance(entry_name, str)
            and unicodedata.normalize("NFKC", entry_name.strip()).casefold() == normalized
        ):
            existing_created = entry.get("created")
            if isinstance(existing_created, str) and existing_created.strip():
                created = existing_created
            existing_id = entry.get("id")
            if isinstance(existing_id, str) and existing_id.strip():
                rating_id = existing_id
            continue

        kept.append(entry)

    kept.append({"name": name, "created": created, "updated": now, "id": rating_id, "rating": rating["rating"]})
    metadata["ratings"] = kept


def _validate_makes(value: object) -> int | None:
    """Validate a ``makes`` counter value for the per-field metadata endpoint."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("'makes' must be a non-negative integer or null")
    return value


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
    MAX_IMAGE_UPLOAD_SIZE = 25 * 1024 * 1024
    MAX_IMAGE_UPLOAD_COUNT = 20

    def __init__(
        self,
        *args,
        source_directory: Path,
        on_markdown_saved: MarkdownSavedCallback | None = None,
        on_recipes_saved: Callable[[list[Path]], None] | None = None,
        on_recipes_deleted: Callable[[list[Path]], None] | None = None,
        on_config_saved: ConfigSavedCallback | None = None,
        config: Configuration | None = None,
        **kwargs,
    ):
        self._source_directory = Path(source_directory).resolve()
        self.on_markdown_saved = on_markdown_saved
        self.on_recipes_saved = on_recipes_saved
        self.on_recipes_deleted = on_recipes_deleted
        self.on_config_saved = on_config_saved
        self.config = config
        super().__init__(*args, **kwargs)

    @property
    def source_directory(self) -> Path:
        """Recipe source directory, following live configuration changes."""
        if self.config is not None and str(self.config.source_directory):
            return Path(self.config.source_directory).resolve()
        return self._source_directory

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path in ("/health", "/health/"):
            self._send_json(200, {"status": "ok"})
            return

        if parsed.path in ("/api/archive/source", "/api/archive/site"):
            self._handle_archive(parsed)
            return

        if parsed.path in ("/api/ai-status", "/api/ai-status/"):
            logger.debug("Received /api/ai-status request")
            try:
                status = ai_recipe.ai_status(self.config)
            except Exception:
                logger.exception("Failed to check local model status")
                self._send_json(500, {"error": "Unable to check local model status"})
                return

            logger.debug(f"Responding to /api/ai-status with {status}")
            self._send_json(200, status)
            return

        if parsed.path in ("/api/config", "/api/config/"):
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
            return

        if parsed.path == "/api/recipe-folders":
            try:
                self._send_json(200, {"folders": self._list_recipe_folders()})
            except OSError:
                logger.exception("Failed to list recipe folders")
                self._send_json(500, {"error": "Unable to list recipe folders"})
            return

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

            if parsed.path.startswith("/api/metadata/"):
                # Handle individual metadata field endpoints
                field_name = parsed.path.split("/")[-1]
                if not field_name:
                    raise ValueError("Expected a metadata field name")
                if field_name == "category":
                    field_name = "categories"

                try:
                    post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
                    metadata = post.metadata

                    if field_name in metadata:
                        # Return the specific field value
                        self._send_json(200, {"value": metadata[field_name]})
                    elif field_name == "categories" and "category" in metadata:
                        self._send_json(200, {"value": metadata["category"]})
                    elif field_name in ("comments", "ratings"):
                        self._send_json(200, {"value": []})
                    else:
                        self._send_json(404, {"error": f"Metadata field '{field_name}' not found"})
                except Exception:
                    logger.exception(f"Failed to parse YAML front matter for field {field_name}")
                    self._send_json(500, {"error": "Unable to parse YAML front matter"})

            elif parsed.path == "/api/recipe-editor":
                try:
                    post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
                except Exception:
                    logger.exception("Failed to parse YAML front matter")
                    self._send_json(500, {"error": "Unable to parse YAML front matter"})
                    return

                self._send_json(
                    200,
                    {
                        "metadata": _editor_metadata(post.metadata),
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

        if parsed.path not in (
            "/api/markdown",
            "/api/recipe-editor",
            "/api/recipe",
            "/api/ai-recipe",
            "/api/config",
            "/api/bulk-editor",
            "/api/bulk-delete",
        ) and not parsed.path.startswith("/api/metadata/"):
            self.send_error(404, "Unknown API endpoint")
            return

        if parsed.path == "/api/config":
            self._handle_config_update()
            return

        if parsed.path == "/api/bulk-editor":
            self._handle_bulk_editor()
            return

        if parsed.path == "/api/bulk-delete":
            self._handle_bulk_delete()
            return

        if parsed.path == "/api/ai-recipe":
            self._handle_ai_recipe()
            return

        if parsed.path == "/api/recipe":
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

            try:
                if create_folder:
                    if not folder:
                        folder_path = self._create_recipe_folder(_recipe_folder_name(content, metadata))
                    else:
                        if folder_path.exists():
                            self._send_json(409, {"error": "That folder already exists"})
                            return
                        folder_path.mkdir(parents=True)
                        folder_path = folder_path.resolve()
                        if not folder_path.is_relative_to(self.source_directory):
                            self._send_json(400, {"error": "Path must stay inside the source directory"})
                            return
                elif not folder_path.is_dir():
                    self._send_json(404, {"error": "Recipe folder not found"})
                    return

                file_path = folder_path / "recipe.md"
                if file_path.exists():
                    self._send_json(409, {"error": "A recipe already exists in that folder"})
                    return

                post_metadata = {key: value for key, value in metadata.items() if value is not None}
                post_metadata["updatedOn"] = (
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                )
                post = frontmatter.Post(content, **post_metadata)
                written_images = self._write_uploaded_images(folder_path, images)
                try:
                    with file_path.open("x", encoding="utf-8", newline="") as recipe_file:
                        recipe_file.write(frontmatter.dumps(post))
                except Exception:
                    self._remove_uploaded_images(written_images)
                    raise

                logger.info("Created recipe: {}", file_path)
                if self.on_markdown_saved is not None:
                    self.on_markdown_saved(file_path)

                self._send_json(
                    201,
                    {
                        "success": True,
                        "path": file_path.relative_to(self.source_directory).as_posix(),
                    },
                )

            except FileExistsError:
                self._send_json(409, {"error": "A recipe or folder already exists at that location"})
            except OSError:
                logger.exception("Failed to create recipe")
                self._send_json(500, {"error": "Unable to create recipe"})
            except Exception:
                logger.exception("Recipe created, but HTML regeneration failed")
                self._send_json(500, {"error": "Recipe created, but HTML regeneration failed"})
            return

        # Handle POST to /api/recipe-editor
        if parsed.path == "/api/recipe-editor":
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

            try:
                if not file_path.is_file():
                    self._send_json(404, {"error": "Markdown file not found"})
                    return

                post = frontmatter.loads(file_path.read_text(encoding="utf-8"))

                # Update editable metadata.
                _apply_editor_metadata(post.metadata, metadata)

                # Migrate the legacy singular field to the canonical plural one.
                post.metadata.pop("category", None)

                # Update the modification timestamp.
                post.metadata["updatedOn"] = (
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                )

                post.content = content
                new_content = frontmatter.dumps(post)

                written_images = self._write_uploaded_images(file_path.parent, images)
                try:
                    file_path.write_text(new_content, encoding="utf-8", newline="")
                except Exception:
                    self._remove_uploaded_images(written_images)
                    raise
                logger.info("Saved recipe editor content: {}", file_path)

                if self.on_markdown_saved is not None:
                    self.on_markdown_saved(file_path)

                self._send_json(200, {"success": True})

            except FileExistsError as exc:
                self._send_json(409, {"error": str(exc)})
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
        elif parsed.path.startswith("/api/metadata/"):
            field_name = parsed.path.split("/")[-1]
            if not field_name:
                self._send_json(400, {"error": "Expected a metadata field name"})
                return
            if field_name == "category":
                field_name = "categories"

            try:
                payload = self._read_json_payload()
                path = payload.get("path")
                value = payload.get("value")

                if not isinstance(path, str):
                    raise ValueError("Expected string field: path")

                if field_name == "ratings":
                    value = _validate_ratings(value)
                elif field_name == "makes":
                    value = _validate_makes(value)

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

                    if field_name == "categories":
                        metadata.pop("category", None)

                    # Reconstruct the file with updated metadata
                    new_content = frontmatter.dumps(post)

                    # Write back to file
                    file_path.write_text(new_content, encoding="utf-8", newline="")
                    logger.info("Updated metadata field '{}' in file: {}", field_name, file_path)

                    if self.on_markdown_saved is not None:
                        try:
                            self.on_markdown_saved(file_path)
                        except Exception:
                            logger.exception("Metadata saved, but recipe regeneration failed")
                            self._send_json(
                                500,
                                {"error": "Metadata saved, but recipe regeneration failed"},
                            )
                            return

                    self._send_json(200, {"success": True, "field": field_name})

                except Exception:
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

    def _regenerate_after_bulk(self, saved: list[Path]) -> bool:
        """Regenerate the site after a bulk write. Returns False on regeneration failure."""
        if not saved:
            return True
        try:
            if self.on_recipes_saved is not None:
                self.on_recipes_saved(saved)
            elif self.on_markdown_saved is not None:
                for path in saved:
                    try:
                        self.on_markdown_saved(path)
                    except Exception:
                        logger.exception("Bulk save: per-recipe regeneration failed for {}", path)
            return True
        except Exception:
            logger.exception("Failed to regenerate the site after a bulk save")
            return False

    def _resolve_bulk_paths(self, payload: dict) -> list[tuple[str, Path]]:
        paths = payload.get("paths")

        if not isinstance(paths, list) or not paths:
            raise ValueError("Expected a non-empty list of paths")
        if len(paths) > 500:
            raise ValueError("Select at most 500 recipes at once")

        resolved: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for item in paths:
            if not isinstance(item, str):
                raise ValueError("Paths must be strings")
            file_path = self._resolve_markdown_path(item)
            key = str(file_path)
            if key in seen:
                continue
            seen.add(key)
            resolved.append((item, file_path))

        return resolved

    def _handle_bulk_editor(self) -> None:
        try:
            payload = self._read_json_payload()
            patch = _validate_bulk_metadata(payload.get("metadata") or {})
            rating = _validate_bulk_rating(payload.get("rating"))
            paths = self._resolve_bulk_paths(payload)

            if not patch and rating is None:
                raise ValueError("Nothing to apply: choose an action for at least one field")
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        saved: list[Path] = []
        failed: list[dict] = []
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        for requested, file_path in paths:
            try:
                if not file_path.is_file():
                    raise ValueError("Markdown file not found")

                post = frontmatter.loads(file_path.read_text(encoding="utf-8"))

                if patch:
                    _apply_bulk_metadata(post.metadata, patch)
                    post.metadata["updatedOn"] = now

                if rating is not None:
                    _apply_bulk_rating(post.metadata, rating)

                file_path.write_text(frontmatter.dumps(post), encoding="utf-8", newline="")
                logger.info("Bulk edited recipe: {}", file_path)
                saved.append(file_path)
            except Exception as exc:
                logger.exception("Failed to bulk edit recipe {}", requested)
                failed.append({"path": requested, "error": str(exc)})

        if not saved:
            self._send_json(
                500,
                {"success": False, "updated": 0, "failed": failed, "error": "No recipes were updated"},
            )
            return

        if not self._regenerate_after_bulk(saved):
            self._send_json(
                500,
                {
                    "success": False,
                    "updated": len(saved),
                    "failed": failed,
                    "error": "Recipes saved, but HTML regeneration failed",
                },
            )
            return

        self._send_json(
            200,
            {"success": not failed, "updated": len(saved), "failed": failed},
        )

    def _handle_bulk_delete(self) -> None:
        try:
            payload = self._read_json_payload()
            paths = self._resolve_bulk_paths(payload)
        except _RequestTooLarge:
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return

        deleted: list[Path] = []
        failed: list[dict] = []

        for requested, file_path in paths:
            try:
                if not file_path.is_file():
                    raise ValueError("Markdown file not found")

                recipe_dir = file_path.parent
                file_path.unlink()

                # Remove the directory too if it is now empty, matching the single-delete behavior.
                if recipe_dir.is_dir() and not any(recipe_dir.iterdir()):
                    recipe_dir.rmdir()

                logger.info("Bulk deleted recipe: {}", file_path)
                deleted.append(file_path)
            except Exception as exc:
                logger.exception("Failed to delete recipe {}", requested)
                failed.append({"path": requested, "error": str(exc)})

        if not deleted:
            self._send_json(
                500,
                {"success": False, "deleted": 0, "failed": failed, "error": "No recipes were deleted"},
            )
            return

        if self.on_recipes_deleted is not None:
            try:
                self.on_recipes_deleted(deleted)
            except Exception:
                logger.exception("Failed to regenerate the site after a bulk delete")
                self._send_json(
                    500,
                    {
                        "success": False,
                        "deleted": len(deleted),
                        "failed": failed,
                        "error": "Recipes deleted, but HTML regeneration failed",
                    },
                )
                return

        self._send_json(
            200,
            {"success": not failed, "deleted": len(deleted), "failed": failed},
        )

    def _handle_config_update(self) -> None:
        try:
            payload = self._read_json_payload()
            if self.config is None:
                raise ValueError("Configuration is not available")
            changed = self.config.apply_config_values(
                payload.get("values")
            )
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

        logger.info("Saved configuration (changed: {})", ", ".join(changed) or "none")
        if self.on_config_saved is not None:
            try:
                self.on_config_saved()
            except Exception:
                logger.exception("Configuration saved, but regeneration failed")
                self._send_json(
                    500, {"error": "Configuration saved, but regeneration failed"}
                )
                return

        self._send_json(
            200,
            {
                "success": True,
                "values": self.config.get_config_values(),
                "changed": changed,
            },
        )

    def _handle_ai_recipe(self) -> None:
        image: tuple[str, bytes] | None = None
        try:
            payload, image = self._read_ai_recipe_payload()
            input_type = payload.get("inputType")
            input_value = payload.get("input")
            stream_progress = payload.get("stream") is True

            if input_type not in {"url", "text", "image"}:
                raise ValueError("Expected inputType to be 'url', 'text', or 'image'")
            if input_type == "image":
                if image is None:
                    raise ValueError("Expected a recipe image upload")
                image = self._validate_uploaded_images([image])[0]
                input_value = image[0]
            elif not isinstance(input_value, str) or not input_value.strip():
                raise ValueError("Expected a non-empty input value")
            elif image is not None:
                raise ValueError("Unexpected uploaded file for this inputType")

        except _RequestTooLarge:
            logger.warning("AI recipe request body was too large")
            self._send_json(413, {"error": "Request body too large"})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning(f"Invalid AI recipe request: {exc}")
            self._send_json(400, {"error": str(exc)})
            return

        if input_type == "image" and image is not None:
            logger.info(
                f"Received AI recipe request from image input "
                f"({image[0]}, {len(image[1])} bytes)"
            )
        else:
            logger.info(f"Received AI recipe request from {input_type} input " f"({len(input_value)} characters)")

        if stream_progress:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            def send_event(event_type: str, **values) -> None:
                body = json.dumps(
                    {"type": event_type, **values}, default=_json_default
                ).encode("utf-8")
                self.wfile.write(body + b"\n")
                self.wfile.flush()

            progress_callback = lambda message: send_event("progress", message=message)
        else:
            send_event = None
            progress_callback = None

        try:
            if input_type == "image" and image is not None:
                result = ai_recipe.generate_recipe(
                    self.config,
                    input_type,
                    image[0],
                    progress_callback=progress_callback,
                    image_bytes=image[1],
                    image_filename=image[0],
                )
            else:
                result = ai_recipe.generate_recipe(
                    self.config,
                    input_type,
                    input_value.strip(),
                    progress_callback=progress_callback,
                )
        except ai_recipe.ModelUnavailable as exc:
            logger.warning(f"Local model unavailable: {exc}")
            if send_event:
                send_event("error", message=str(exc))
            else:
                self._send_json(503, {"error": str(exc)})
        except (ai_recipe.ModelRequestError, ai_recipe.SourceFetchError) as exc:
            logger.warning(f"AI recipe generation failed: {exc}")
            if send_event:
                send_event("error", message=str(exc))
            else:
                self._send_json(502, {"error": str(exc)})
        except ValueError as exc:
            logger.warning(f"Invalid AI recipe input: {exc}")
            if send_event:
                send_event("error", message=str(exc))
            else:
                self._send_json(400, {"error": str(exc)})
        except Exception:
            logger.exception("Failed to generate a recipe with the local model")
            if send_event:
                send_event("error", message="Unable to generate recipe")
            else:
                self._send_json(500, {"error": "Unable to generate recipe"})
        else:
            logger.info(f"AI recipe generation succeeded " f"({len(result.get('content', ''))} characters of Markdown)")
            if send_event:
                send_event("result", result=result)
            else:
                self._send_json(200, result)

    def _read_ai_recipe_payload(self) -> tuple[dict, tuple[str, bytes] | None]:
        """Read an AI recipe request, which may carry a multipart image upload."""
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            return self._read_json_payload(), None

        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("Missing Content-Length")
        try:
            length = int(content_length)
        except ValueError:
            raise ValueError("Invalid Content-Length") from None
        if length < 0:
            raise ValueError("Invalid Content-Length")
        if length > self.MAX_IMAGE_UPLOAD_SIZE:
            raise _RequestTooLarge("Image upload request too large")

        body = self.rfile.read(length)
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        if not message.is_multipart():
            raise ValueError("Invalid multipart request")

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

    def _read_json_payload(self) -> dict:
        content_length = self.headers.get("Content-Length")

        if content_length is None:
            raise ValueError("Missing Content-Length")

        try:
            length = int(content_length)
        except ValueError:
            raise ValueError("Invalid Content-Length") from None

        if length < 0:
            raise ValueError("Invalid Content-Length")

        if length > self.MAX_REQUEST_SIZE:
            raise _RequestTooLarge("Request body too large")

        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc.msg}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")

        return payload

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

        directory = (
            self.source_directory if kind == "source" else Path(self.directory).resolve()
        )

        if not directory.is_dir():
            self._send_json(404, {"error": "Archive directory not found"})
            return

        archive_path = Path()
        headers_sent = False
        try:
            with tempfile.NamedTemporaryFile(
                prefix="recipeserver-", suffix=".7z", delete=False
            ) as temp:
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
                while chunk := archive_file.read(64 * 1024):
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

    def _read_recipe_payload(self) -> tuple[dict, list[tuple[str, bytes]]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            return self._read_json_payload(), []

        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("Missing Content-Length")
        try:
            length = int(content_length)
        except ValueError:
            raise ValueError("Invalid Content-Length") from None
        if length < 0:
            raise ValueError("Invalid Content-Length")
        if length > self.MAX_IMAGE_UPLOAD_SIZE:
            raise _RequestTooLarge("Image upload request too large")

        body = self.rfile.read(length)
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        if not message.is_multipart():
            raise ValueError("Invalid multipart request")

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

    def do_DELETE(self):
        parsed = urlsplit(self.path)

        if parsed.path != "/api/recipe":
            self.send_error(404, "Unknown API endpoint")
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

            # Get the directory containing the recipe
            recipe_dir = file_path.parent

            # Only delete the recipe.md file itself - don't delete other files in the directory
            try:
                # Delete the recipe.md file
                file_path.unlink()

                # Directory cleanup - if the directory is now empty, remove it too
                if not any(recipe_dir.iterdir()):
                    recipe_dir.rmdir()

            except Exception:
                logger.exception("Failed to delete recipe")
                self._send_json(500, {"error": "Unable to delete recipe"})
                return

            logger.info("Deleted recipe: {}", file_path)
            self._send_json(200, {"success": True})

        except OSError:
            logger.exception("Failed to delete recipe")
            self._send_json(500, {"error": "Unable to delete recipe"})

    def _validate_uploaded_images(self, images: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
        if len(images) > self.MAX_IMAGE_UPLOAD_COUNT:
            raise ValueError(f"Upload no more than {self.MAX_IMAGE_UPLOAD_COUNT} images at a time")

        validated = []
        names = set()
        total_size = 0
        for filename, content in images:
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
            if PureWindowsPath(filename.split(".", 1)[0]).name.upper() in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{number}" for number in range(1, 10)),
                *(f"LPT{number}" for number in range(1, 10)),
            }:
                raise ValueError("Invalid image filename")

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
    def _validate_image_content(filename: str, content: bytes) -> None:
        extension = Path(filename).suffix.lower()
        if extension == ".svg":
            if b"<!doctype" in content.lower():
                raise ValueError(f"Invalid SVG image: {filename}")
            try:
                root = ET.fromstring(content)
            except ET.ParseError as exc:
                raise ValueError(f"Invalid SVG image: {filename}") from exc
            if root.tag.rsplit("}", 1)[-1].lower() != "svg":
                raise ValueError(f"Invalid SVG image: {filename}")

            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1].lower() in {"script", "foreignobject"}:
                    raise ValueError(f"SVG contains unsupported active content: {filename}")
                for attribute, value in element.attrib.items():
                    if attribute.rsplit("}", 1)[-1].lower().startswith("on"):
                        raise ValueError(f"SVG contains unsupported active content: {filename}")
                    if attribute.rsplit("}", 1)[-1].lower() in {"href", "style"} and (
                        ("url(" in value.lower() and "url(#" not in value.lower())
                        or (attribute.lower().endswith("href") and not value.startswith("#"))
                    ):
                        raise ValueError(f"SVG contains unsupported external content: {filename}")
            return

        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError(f"Invalid image file: {filename}") from exc

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


class Server:
    def __init__(
        self,
        cfg: Configuration,
        on_markdown_saved: MarkdownSavedCallback | None = None,
        on_config_saved: ConfigSavedCallback | None = None,
        on_recipes_saved: RecipesSavedCallback | None = None,
        on_recipes_deleted: RecipesSavedCallback | None = None,
    ):
        self.cfg = cfg
        self.on_markdown_saved = on_markdown_saved
        self.on_config_saved = on_config_saved
        self.on_recipes_saved = on_recipes_saved
        self.on_recipes_deleted = on_recipes_deleted
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
            on_config_saved=self.on_config_saved,
            on_recipes_saved=self.on_recipes_saved,
            on_recipes_deleted=self.on_recipes_deleted,
            config=self.cfg,
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
