"""HTTP server for the generated recipe site and its editing APIs.

The request handler is intentionally split into small, focused helpers: routing
methods dispatch to endpoint handlers, endpoint handlers validate input and
coordinate I/O, and shared helpers handle payload parsing, path safety, and
metadata updates.
"""

from __future__ import annotations

import base64
import difflib
import html
import json
import shutil
import re
import socket
import sys
import tempfile
import time
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
from mimetypes import guess_type
from pathlib import Path, PureWindowsPath
from threading import Thread
from urllib.parse import parse_qs, quote, unquote, urlsplit

import frontmatter
from PIL import Image, UnidentifiedImageError

from . import ai_assistant, ai_recipe, assistant_render
from . import history as recipe_history
from .authorization import MUTATING_METHODS, AuthManager, Decision, Permission
from .oidc import FLOW_TTL_SECONDS, OIDCError
from .retention import get_retention_manager
from .session import FLOW_COOKIE, SESSION_COOKIE, clear_cookie_header, cookie_header, parse_cookies
from ._logger import logger
from .archive import ARCHIVE_KINDS, archive_filename, create_archive, resolve_archive_date
from .config import (
    Configuration,
    DEFAULT_KEEP_ALIVE_MINUTES,
    DEFAULT_SERVER_BIND_ADDRESS,
    DEFAULT_SERVER_PORT,
    DEFAULT_TRANSCRIPTION_ENDPOINT,
    DEFAULT_TRANSCRIPTION_MODEL,
    _validate_keep_alive_minutes,
    _validate_transcription_endpoint,
    _validate_transcription_model,
)
from .image_handler import IMAGE_EXTENSIONS
from .metadata_options import collect_metadata_options
from .recipe_paths import RECIPE_FILENAME, display_path, resolve_recipe_file, resolve_recipe_folder
from .shopping_list import scrape_ingredients
from .recipe_utils import (
    CATEGORIES_FIELD,
    LEGACY_CATEGORY_FIELD,
    canonical_recipe_id,
    clean_source_fields,
    collapse_status,
    extract_recipe_id,
    is_finite_rating_score,
    is_valid_recipe_id,
    json_default,
    new_recipe_id,
    normalize_legacy_category,
    normalize_reviewer_name,
    normalize_source_dict,
    set_recipe_id,
)
from .transcriber import TranscriberUnavailable, TranscriptionError, get_transcriber

MarkdownSavedCallback = Callable[[Path], None]
ConfigSavedCallback = Callable[[], None]
RecipesDeletedCallback = Callable[[list[Path]], None]

# ----- Request and server constants ----------------------------------------
# These values define request-size limits and the local server's network
# behavior. Keep them discoverable here rather than buried in handlers.

BULK_MAX_PATHS = 100
ARCHIVE_STREAM_CHUNK_BYTES = 64 * 1024

# The default bind address accepts connections on every IPv4 interface so the
# site is reachable from the local network (for example as
# http://<hostname>.local:8000). The site has no authentication: anyone who
# can reach this machine can load and edit recipes over plain HTTP. Set
# server_bind_address to 127.0.0.1 to accept connections from this machine
# only — that is what the HTTPS-terminating reverse proxy setup needs.
# 127.0.0.1 is used for the *default loopback fallbacks* instead of
# "localhost" because the name may resolve to IPv6 first, which the IPv4
# socket does not listen on.
LOCALHOST = "127.0.0.1"
IPV6_WILDCARD = "::"
IPV6_LOOPBACK = "::1"
IPV4_WILDCARD = "0.0.0.0"
WILDCARD_BIND_ADDRESSES = {IPV6_WILDCARD, IPV4_WILDCARD}

# Audio containers the browser can record, mapped to the file suffix the
# recording is written to before it is transcribed.
TRANSCRIPTION_AUDIO_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".mp4",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
}

# Longest recording the transcription endpoint accepts.
MAX_TRANSCRIPTION_SIZE = 25 * 1024 * 1024

# Built-in speech sample the Configuration dialog posts through
# /api/config/test-transcription to verify the configured Ollama server and
# model actually transcribe audio ("Add two cups of flour and one cup of
# sugar."). Bundled with the package; the browser microphone is not used.
TRANSCRIPTION_TEST_SAMPLE_PATH = Path(__file__).resolve().parent / "TranscriptionTestSample.wav"

# The shared transcriber. It is stateless — the Ollama server and its model
# are managed independently of this app; each request reads the transcription
# settings from the live configuration.
transcriber = get_transcriber()

# ----- Filename and metadata-field rules -----------------------------------
# Shared by recipe creation, the metadata endpoints, and image validation.

RECIPE_FOLDER_NAME_MAX_BYTES = 200
MAX_RATING_NAME_LENGTH = 100
MARKDOWN_NOT_FOUND_ERROR = "Markdown file not found"

# Windows device names that may not be used as filenames (with or without an
# extension). Applied to both recipe folder names and image filenames.
WINDOWS_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{number}" for number in range(1, 10)} | {f"LPT{number}" for number in range(1, 10)}
)

# SVG elements that can carry executable or externally loaded content.
_SVG_BLOCKED_TAGS = frozenset({"script", "foreignobject"})


class _RequestTooLarge(ValueError):
    """Raised when a request body exceeds the accepted size."""


class _StreamClosed(Exception):
    """Raised when the browser closes an in-progress event stream."""


def _contents_equivalent(old: str, new: str) -> bool:
    """Return True when two recipe documents carry the same content.

    ``updatedOn`` is ignored so a save that only bumps the edit timestamp
    counts as unchanged. Documents that fail to parse fall back to a byte
    comparison.
    """
    if old == new:
        return True
    try:
        old_post = frontmatter.loads(old)
        new_post = frontmatter.loads(new)
    except Exception:
        return False
    old_metadata = dict(old_post.metadata)
    new_metadata = dict(new_post.metadata)
    old_metadata.pop("updatedOn", None)
    new_metadata.pop("updatedOn", None)
    # The editor round-trips every editor-managed field, including ones the
    # user never set, writing explicit nulls. A null-valued key carries no
    # more information than an absent one, so it is ignored for change
    # detection. (Clearing a field changes it from a value to null, which
    # still counts as a change.)
    old_metadata = {key: value for key, value in old_metadata.items() if value is not None}
    new_metadata = {key: value for key, value in new_metadata.items() if value is not None}
    return old_metadata == new_metadata and old_post.content == new_post.content


def _save_recipe_contents(
    path: Path, new_content: str, *, exclusive: bool = False, force_recipe_id: str | None = None, create_parents: bool = False
) -> bool:
    """Write *new_content* to *path*, snapshotting the previous version.

    This is the common save mechanism for every RecipeServer-managed
    modification of a recipe: the existing document is preserved as an
    immutable history snapshot immediately before its contents are replaced,
    and the recipe's identity (``recipe_id``) is preserved across the write.
    An unchanged save writes nothing and creates no snapshot.

    Returns True when the file was written, False when it was unchanged.

    Raises:
        recipe_history.HistoryError: the previous version could not be snapshotted;
            the save is aborted so the recipe file is left untouched.
        FileExistsError: *exclusive* was set and *path* already exists.
        OSError: the file could not be written; any snapshot created for this
            save is rolled back so the history holds no duplicate of the
            unchanged recipe.
    """
    old_content = path.read_text(encoding="utf-8") if path.exists() else None

    if exclusive and old_content is not None:
        raise FileExistsError(f"Recipe already exists: {path}")

    if old_content is not None and _contents_equivalent(old_content, new_content):
        logger.info(f"Skipping unchanged save for {path}")
        return False

    # Resolve identity: keep the existing recipe's id, or mint a fresh one for
    # a new recipe (or honor *force_recipe_id*, used when restoring a deleted
    # recipe whose current file is gone), and force it into the saved content.
    existing_id = extract_recipe_id(old_content) if old_content is not None else None
    resolved_id = existing_id or force_recipe_id or new_recipe_id()
    new_content = set_recipe_id(new_content, resolved_id)

    snapshot_path: Path | None = None
    if old_content is not None:
        snapshot_path = recipe_history.create_snapshot(resolved_id, old_content)

    try:
        if exclusive:
            if create_parents:
                path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="") as recipe_file:
                recipe_file.write(new_content)
        else:
            if create_parents:
                path.parent.mkdir(parents=True, exist_ok=True)
            recipe_history.write_file_atomic(path, new_content)
    except BaseException:
        # The recipe was not replaced; drop the snapshot so an unchanged
        # recipe never occupies a history slot.
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)
        raise

    # Throttled background retention; never blocks the save.
    get_retention_manager().schedule_recipe_prune(resolved_id)
    return True


_PREVIEW_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_PREVIEW_HEADER_RE = re.compile(r"<header class=\"recipe-header\">.*?</header>", re.DOTALL | re.IGNORECASE)


def _sanitize_preview_html(rendered: str) -> str:
    """Neutralize a rendered recipe page for use as a historical preview.

    The preview must not run any scripts (the current recipe's page would be
    mutated by them) and hides the page chrome, since the historical version
    is being shown inside the history dialog.
    """
    without_scripts = _PREVIEW_SCRIPT_RE.sub("", rendered)
    return _PREVIEW_HEADER_RE.sub("", without_scripts)


def _read_recipe_post(path: Path) -> frontmatter.Post:
    """Parse a recipe file's front matter, raising on failure."""
    return frontmatter.loads(path.read_text(encoding="utf-8"))


def _update_recipe_post(path: Path, mutate: Callable[[frontmatter.Post], None]) -> tuple[frontmatter.Post, bool]:
    """Read a recipe's front matter, apply *mutate*, and rewrite the file.

    Returns the updated post and whether the file was actually written.
    """
    post = _read_recipe_post(path)
    mutate(post)
    changed = _save_recipe_contents(path, frontmatter.dumps(post))
    return post, changed


def _now_utc_iso() -> str:
    """Current UTC time as a millisecond ISO string ending in ``Z``."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _is_windows_reserved_name(stem: str) -> bool:
    """Check a filename stem (no extension) against Windows reserved device names."""
    return stem.upper() in WINDOWS_RESERVED_FILENAMES


def _xml_local_name(name: str) -> str:
    """Strip any XML namespace from a tag or attribute name."""
    return name.rsplit("}", 1)[-1].lower()


def _canonical_category_field(field_name: str) -> str:
    """Map the legacy singular ``category`` field name onto ``categories``."""
    return CATEGORIES_FIELD if field_name == LEGACY_CATEGORY_FIELD else field_name


def _metadata_field_name(path: str) -> str | None:
    """Extract the metadata field name from an API path, if present."""
    field_name = path.rsplit("/", 1)[-1]
    return _canonical_category_field(field_name) if field_name else None


def _drop_legacy_category(metadata: dict) -> None:
    """Remove the legacy singular field once the plural one has been written."""
    metadata.pop(LEGACY_CATEGORY_FIELD, None)


# ---------------------------------------------------------------------------
# Editor metadata schema and validation
# ---------------------------------------------------------------------------

EDITOR_METADATA_FIELDS = {
    "tags": "string_list",
    "cuisine": "string_list",
    "categories": "string_list",
    "meals": "string_list",
    "makes": "non_negative_integer",
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


def _editor_metadata(metadata: dict) -> dict:
    """Return editable metadata, mapping the legacy singular category field."""
    merged = dict(metadata)
    normalize_legacy_category(merged)
    values = {field: merged.get(field) for field in EDITOR_METADATA_FIELDS}

    # Status is a single string; older recipes may store a list.
    values["status"] = collapse_status(values.get("status"))

    # The editor edits one source at a time; older recipes may store a list.
    values["source"] = normalize_source_dict(values["source"])

    # ``archived`` defaults to False when absent (or not a boolean).
    values["archived"] = metadata.get("archived") is True

    return values


def _source_is_empty(source: dict | None) -> bool:
    return not source or not any(value is not None for value in source.values())


def _recipe_folder_name(content: str, metadata: dict) -> str:
    heading = re.search(r"^\s{0,3}#\s+(?P<heading>.+?)\s*#*\s*$", content, re.MULTILINE)
    title = heading.group("heading") if heading else metadata.get("title")
    if not isinstance(title, str):
        title = ""

    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title)
    name = " ".join(name.split()).strip(" .")
    if not name:
        name = "New Recipe"

    encoded_name = name.encode("utf-8")[:RECIPE_FOLDER_NAME_MAX_BYTES]
    name = encoded_name.decode("utf-8", errors="ignore").rstrip(" .") or "New Recipe"
    if _is_windows_reserved_name(name):
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
        source = normalize_source_dict(value)
        if source is None:
            return None
    elif not isinstance(value, dict):
        raise ValueError(f"'{field}' must be an object or null")
    else:
        source = value
    return clean_source_fields(source)


def _validate_editor_field(field: str, expected_type: str, value: object) -> object:
    validators = {
        "string_list": _validate_string_list_field,
        "string": _validate_string_field,
        "non_negative_integer": lambda field, value: _validate_makes(value),
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


def _validate_assistant_metadata(metadata: object) -> dict:
    """Validate a partial editor-metadata object for the AI assistant.

    Only the keys present are validated and returned; ``updatedOn`` (which
    the server always manages) and unknown fields are rejected, so a
    misbehaving model cannot sneak in an arbitrary front-matter key. A
    value of null clears the field, matching the editor's semantics.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Expected a metadata object")

    validated = {}
    for key, value in metadata.items():
        if key == "updatedOn":
            raise ValueError("'updatedOn' is managed by the server")
        expected_type = EDITOR_METADATA_FIELDS.get(key)
        if expected_type is None:
            raise ValueError(f"Unknown metadata field: {key}")
        if value is None:
            validated[key] = None
        else:
            validated[key] = _validate_editor_field(key, expected_type, value)

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


def _validate_rating_name(name: object, label: str) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_RATING_NAME_LENGTH:
        raise ValueError(f"{label} must be 1 to {MAX_RATING_NAME_LENGTH} characters")
    return name.strip()


def _validate_rating_score(score: object, label: str) -> int | float:
    if not is_finite_rating_score(score):
        raise ValueError(f"{label} must be a number between 0 and 10")
    if score < 0 or score > 10:
        raise ValueError(f"{label} must be between 0 and 10")
    return score


def _validate_bulk_rating(value: object) -> tuple[str, int | float] | None:
    """Validate a bulk rating override: add a named rating, overriding ties."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("'rating' must be an object with 'name' and 'rating'")

    name = _validate_rating_name(value.get("name"), "'rating.name'")
    score = _validate_rating_score(value.get("rating", value.get("score")), "'rating.rating'")
    return name, score


# ---------------------------------------------------------------------------
# Rating validation and updates
# ---------------------------------------------------------------------------


def _apply_rating_override(ratings: object, name: str, score: int | float) -> list[dict]:
    """Return ratings with the named rating added or overridden in place."""
    current = ratings if isinstance(ratings, list) else []
    updated: list[dict] = []
    replaced = False
    normalized = normalize_reviewer_name(name)
    now = _now_utc_iso()

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

    label = f"Rating {index + 1}"
    name = _validate_rating_name(rating.get("name"), label)
    rating_id = rating.get("id")
    score = _validate_rating_score(rating.get("rating"), label)

    if not isinstance(rating_id, str) or not rating_id.strip() or rating_id != rating_id.strip():
        raise ValueError(f"{label} must have an ID")

    for field in ("created", "updated"):
        timestamp = rating.get(field)
        if not isinstance(timestamp, str):
            raise ValueError(f"Rating {index + 1} must have a {field} timestamp")
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Rating {index + 1} has an invalid {field} timestamp") from exc

    normalized_rating = rating.copy()
    normalized_rating["name"] = name
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


# ----- image listing and renaming helpers -----------------------------------
# The editor lets people see the images that sit next to a recipe Markdown
# file, rename them, and promote one to the first image link in the Markdown
# (the recipe page hero). These helpers keep the rules in one place.


def _image_name_pattern(name: str) -> re.Pattern:
    """Match ``name`` only when it is not glued to more filename characters.

    A plain substring replace would corrupt references such as
    ``chocolate-cake.png`` when renaming ``cake.png``.
    """
    return re.compile(r"(?P<prefix>^|[^A-Za-z0-9_.-])" + re.escape(name) + r"(?![A-Za-z0-9_.-])")


def _replace_image_reference(content: str, source: str, target: str) -> str:
    updated = _image_name_pattern(source).sub(lambda match: match.group("prefix") + target, content)
    quoted_source = quote(source)
    if quoted_source != source:
        updated = _image_name_pattern(quoted_source).sub(lambda match: match.group("prefix") + quote(target), updated)
    return updated


# Match a Markdown image reference: the src token (optionally in angle brackets)
# followed by an optional title and the closing paren. Only the src is captured.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*(?P<image_src><[^>\n]*>|[^)\s>]+)(?:(?:\s+\"[^\"]*\")?\s*\))")
_HTML_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"'](?P<image_src>[^\"']+)[\"']", re.IGNORECASE)
_EXTERNAL_SRC_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def _is_external_src(src: str) -> bool:
    return _EXTERNAL_SRC_RE.match(src) is not None


def _basename_of_src(src: str) -> str:
    clean = src.split("?", 1)[0].split("#", 1)[0]
    clean = clean.replace("&amp;", "&").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    segments = [segment for segment in clean.split("/") if segment]
    return unquote(segments[-1]) if segments else ""


def _first_image_reference(content: str) -> dict | None:
    """Locate the first image in the Markdown, Markdown or HTML syntax."""
    candidates: list[dict] = []
    for match in _MARKDOWN_IMAGE_RE.finditer(content):
        src_raw = match.group("image_src")
        src = src_raw[1:-1] if src_raw.startswith("<") and src_raw.endswith(">") else src_raw
        candidates.append(
            {
                "span_start": match.start(),
                "span_end": match.end(),
                "src_start": match.start("image_src"),
                "src_end": match.end("image_src"),
                "src": src,
                "kind": "markdown",
            }
        )
    for match in _HTML_IMG_RE.finditer(content):
        span_end = match.end()
        closing = content.find(">", match.end())
        if closing != -1:
            span_end = closing + 1
        candidates.append(
            {
                "span_start": match.start(),
                "span_end": span_end,
                "src_start": match.start("image_src"),
                "src_end": match.end("image_src"),
                "src": match.group("image_src"),
                "kind": "html",
            }
        )
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate["span_start"])


def _remove_image_span(content: str, span_start: int, span_end: int) -> str:
    """Remove the image; when it sits alone on its line, drop the line too."""
    line_start = content.rfind("\n", 0, span_start) + 1
    line_end_index = content.find("\n", span_end)
    line_end = line_end_index if line_end_index != -1 else len(content)
    before = content[line_start:span_start]
    after = content[span_end:line_end]
    if before.strip() == "" and after.strip() == "":
        remove_end = line_end + 1 if line_end < len(content) and content[line_end] == "\n" else line_end
        return content[:line_start] + content[remove_end:]
    return content[:span_start] + content[span_end:]


def _fallback_main_image(content: str, deleted_name: str, remaining_names: list[str]) -> tuple[str | None, str | None]:
    """Point the main image at a still-existing file after a delete.

    The main image is the first image link in the Markdown. If it pointed at
    the deleted file, rewrite it to the first remaining image alphabetically;
    with none remaining, remove the dangling link. Returns
    (updated_content, fallback_name) or (None, None) when nothing changed.
    """
    first = _first_image_reference(content)
    if first is None or _is_external_src(first["src"]):
        return None, None
    if _basename_of_src(first["src"]) != deleted_name:
        return None, None

    if remaining_names:
        target = remaining_names[0]
        if first["kind"] == "html":
            replacement = target.replace("&", "&amp;").replace('"', "&quot;")
        elif re.search(r"[\s<>()]", target):
            replacement = f"<{target}>"
        else:
            replacement = target
        return content[: first["src_start"]] + replacement + content[first["src_end"] :], target

    return _remove_image_span(content, first["span_start"], first["span_end"]), None


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

    if _is_windows_reserved_name(filename.split(".", 1)[0]):
        raise ValueError("Invalid image filename")


def _validate_svg_attribute(filename: str, attribute: str, value: str) -> None:
    """Reject event-handler attributes and external references in an SVG."""
    attr_name = _xml_local_name(attribute)
    if attr_name.startswith("on"):
        raise ValueError(f"SVG contains unsupported active content: {filename}")

    if attr_name not in {"href", "style"}:
        return

    lowered_value = value.lower()
    references_external_url = "url(" in lowered_value and "url(#" not in lowered_value
    references_external_href = attribute.lower().endswith("href") and not value.startswith("#")
    if references_external_url or references_external_href:
        raise ValueError(f"SVG contains unsupported external content: {filename}")


def _validate_image_name(name: str, *, field: str) -> str:
    """Validate a bare image filename (no directories) for the rename API."""
    try:
        _validate_image_filename(name)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc
    if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"{field} must keep a supported image extension ({', '.join(sorted(IMAGE_EXTENSIONS))})")
    return name


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
        auth: AuthManager | None = None,
        **kwargs,
    ):
        self._source_directory = Path(source_directory).resolve()
        self.on_markdown_saved = on_markdown_saved
        self.on_config_saved = on_config_saved
        self.on_recipes_deleted = on_recipes_deleted
        self.config = config
        self.auth = auth
        self._identity = None
        # Headers queued by handlers (e.g. Set-Cookie) are emitted by end_headers.
        self._pending_headers: list[tuple[str, str]] = []
        self._response_status = 200
        super().__init__(*args, **kwargs)

    # Speak HTTP/1.1 so a browser reuses one keep-alive connection per host
    # instead of opening a fresh TCP connection for every asset (the
    # HTTP/1.0 default). Through a tunnel or relay such as Tailscale each
    # connection is round-trip-expensive and prone to being dropped; a
    # dropped connection then surfaces as a missing stylesheet or script,
    # which looked like the page failing to style (sometimes fully, sometimes
    # halfway, sometimes losing only one script).
    protocol_version = "HTTP/1.1"

    def send_response_only(self, code, message=None):
        self._response_status = code
        super().send_response_only(code, message)

    def _has_buffered_header(self, name: bytes) -> bool:
        prefix = name.lower()
        return any(line.lower().startswith(prefix) for line in getattr(self, "_headers_buffer", []))

    @property
    def source_directory(self) -> Path:
        """Recipe source directory, following live configuration changes."""
        configured = getattr(self.config, "source_directory", "") if self.config is not None else ""
        if str(configured):
            return Path(configured).resolve()
        return self._source_directory

    # ----- routing ---------------------------------------------------------

    def end_headers(self):
        # Generated HTML must never be served from a stale cache: the editor
        # reloads the page immediately after a save and has to see the
        # freshly generated page, so HTML (and directory URLs) are sent
        # `no-store`. Everything else revalidates instead of trusting
        # heuristic caching: the static-file fallback always sends
        # Last-Modified, so `no-cache` still allows cheap 304s while making
        # sure a rebuilt asset is picked up on the next load.
        # `self.path` does not exist yet when an error response is issued
        # before the request line was parsed (any byte sequence the parser
        # rejects — e.g. a client speaking TLS at this plain-HTTP port).
        # `end_headers` must still emit the response: a proxy in front of
        # this server turns a connection that closes with zero bytes into
        # a 502 Bad Gateway instead of the 400 it should be.
        path = urlsplit(getattr(self, "path", "") or "").path
        if not self._has_buffered_header(b"cache-control"):
            if path.endswith(".html") or path.endswith("/"):
                self.send_header("Cache-Control", "no-store")
            else:
                self.send_header("Cache-Control", "no-cache")
        # HTTP/1.1 keep-alive requires every response to declare its length.
        # The directory redirect the static handler issues carries no body and
        # no Content-Length, which would leave a keep-alive client waiting
        # for a body that never ends. Streaming responses (SSE, archives) set
        # Connection: close and close-delimit their body (self.close_connection),
        # and 1xx/204/205/304 must not carry a Content-Length at all, so only
        # fill in the empty body the other responses above never write.
        status = self._response_status
        if (
            not self.close_connection
            and not 100 <= status < 200
            and status not in (204, 205, 304)
            and not self._has_buffered_header(b"content-length")
            and not self._has_buffered_header(b"transfer-encoding")
        ):
            self.send_header("Content-Length", "0")
        for name, value in self._pending_headers:
            self.send_header(name, value)
        self._pending_headers = []
        super().end_headers()

    # ----- authentication gate ----------------------------------------------

    def _auth_gate(self, method: str) -> bool:
        """Enforce authentication/authorization before any dispatch.

        Returns True when a response was sent and the caller must stop. The
        gate also covers generated static pages and ``HEAD`` requests, which
        would otherwise bypass the API dispatcher entirely.
        """
        auth = self.auth
        if auth is None or not auth.enabled:
            return False

        path = urlsplit(getattr(self, "path", "") or "").path
        result = auth.decide(path, method, self.headers, parse_cookies(self.headers.get("Cookie")))
        self._identity = result.identity
        if result.decision is Decision.ALLOW:
            return False
        # An early error response must still consume the request body. With
        # HTTP/1.1 keep-alive, unread bytes (e.g. a POST's "{}") are parsed as
        # the start of the next request line, producing 501 "Unsupported
        # method ('{}GET')" on the following request.
        if method.upper() in MUTATING_METHODS:
            self._discard_request_body()
        if result.decision is Decision.LOGIN:
            login_url = auth.login_url(path)
            if path.startswith("/api/"):
                self._send_json(401, {"error": "Authentication required", "loginUrl": login_url})
            else:
                self._redirect_to(login_url)
            return True
        if path.startswith("/api/"):
            self._send_json(403, {"error": "You do not have permission to do that"})
        else:
            self._send_auth_error(403, "Access denied", "You do not have permission to view this page.")
        return True

    def _discard_request_body(self) -> None:
        """Drain a declared request body so the next keep-alive request is clean."""
        header = self.headers.get("Content-Length")
        if not header:
            return
        try:
            length = int(header)
        except ValueError:
            self.close_connection = True
            return
        if length <= 0:
            return
        if length > self.MAX_IMAGE_UPLOAD_SIZE:
            # Do not block on a body we are not going to use.
            self.close_connection = True
            return
        try:
            self.rfile.read(length)
        except OSError:
            self.close_connection = True

    def _redirect_to(self, location: str) -> None:
        """Send a short redirect body; cookies are supplied via pending headers."""
        body = b"<!doctype html><html><head><meta charset='utf-8'><title>Redirecting</title></head><body><p>Redirecting&hellip;</p></body></html>"
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_auth_error(self, status: int, title: str, message: str) -> None:
        """Render a generic, non-leaking authentication error page."""
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title></head><body>"
            f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></body></html>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _queue_cookie(self, name: str, value: str, max_age: int) -> None:
        """Queue a Set-Cookie header using the live auth configuration."""
        secure = bool(self.auth and self.auth.settings.secure_cookies)
        self._pending_headers.append(("Set-Cookie", cookie_header(name, value, max_age, secure=secure)))

    def do_HEAD(self):
        if self._auth_gate("HEAD"):
            return
        super().do_HEAD()

    def do_GET(self):
        if self._auth_gate("GET"):
            return
        parsed = urlsplit(self.path)
        path = parsed.path

        if self._dispatch_get_api(path, parsed):
            return

        if path.startswith("/api/"):
            self.send_error(404, "Unknown API endpoint")
            return

        super().do_GET()

    def _dispatch_get_api(self, path: str, parsed) -> bool:
        path = path.rstrip("/") or "/"
        simple_handlers = {
            "/health": self._handle_health,
            "/api/auth/status": self._handle_auth_status,
            "/api/auth/login": self._handle_auth_login,
            "/api/auth/callback": self._handle_auth_callback,
            "/api/auth/settings": self._handle_auth_settings_get,
            "/api/ai-status": self._handle_ai_status,
            "/api/config": self._handle_config_get,
            "/api/metadata-options": self._handle_metadata_options,
            "/api/recipe-folders": self._handle_recipe_folders_get,
            "/api/bulk-editor": lambda: self._handle_bulk_editor_get(parsed),
            "/api/shopping-list": lambda: self._handle_shopping_list_get(parsed),
        }

        if path in simple_handlers:
            simple_handlers[path]()
            return True
        if path in ("/api/archive/source", "/api/archive/site"):
            self._handle_archive(parsed)
            return True
        if path == "/api/history":
            self._handle_history_list(parsed)
            return True
        if path == "/api/history/preview":
            self._handle_history_preview(parsed)
            return True
        if path == "/api/history/compare":
            self._handle_history_compare(parsed)
            return True
        if path == "/api/markdown":
            self._handle_markdown_read(parsed)
            return True
        if path == "/api/recipe-editor":
            self._handle_recipe_editor_read(parsed)
            return True
        if path.startswith("/api/metadata/"):
            self._handle_metadata_read(parsed)
            return True
        return False

    def do_POST(self):
        if self._auth_gate("POST"):
            return
        path = urlsplit(self.path).path

        if self._dispatch_post_api(path):
            return

        self.send_error(404, "Unknown API endpoint")

    def _dispatch_post_api(self, path: str) -> bool:
        path = path.rstrip("/") or "/"
        exact_handlers = {
            "/api/auth/logout": self._handle_auth_logout,
            "/api/auth/settings": self._handle_auth_settings_post,
            "/api/bulk-editor": self._handle_bulk_editor_post,
            "/api/bulk-delete": self._handle_bulk_delete,
            "/api/config": self._handle_config_update,
            "/api/config/test-transcription": self._handle_test_transcription,
            "/api/ai-recipe": self._handle_ai_recipe,
            "/api/ai-assistant": self._handle_ai_assistant,
            "/api/assistant-markdown": self._handle_assistant_markdown,
            "/api/recipe": self._handle_recipe_create,
            "/api/recipe-editor": self._handle_recipe_editor_post,
            "/api/recipe-images/rename": self._handle_recipe_images_rename_post,
            "/api/recipe-images/upload": self._handle_recipe_images_upload_post,
            "/api/recipe-images/delete": self._handle_recipe_images_delete_post,
            "/api/markdown": self._handle_markdown_post,
            "/api/history/restore": self._handle_history_restore,
            "/api/transcribe": self._handle_transcription,
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
        if self._auth_gate("DELETE"):
            return
        parsed = urlsplit(self.path)
        if parsed.path != "/api/recipe":
            self.send_error(404, "Unknown API endpoint")
            return
        self._handle_recipe_delete(parsed)

    # ----- shared endpoint helpers ------------------------------------------
    # Small building blocks shared by the endpoint handlers: standard error
    # responses, Markdown-path resolution, and post-save notification.

    def _send_payload_error(self, exc: Exception) -> None:
        """Send the standard response for a failed request-body parse."""
        if isinstance(exc, _RequestTooLarge):
            self._send_json(413, {"error": "Request body too large"})
            return
        self._send_json(400, {"error": str(exc)})

    def _require_markdown_file(self, file_path: Path, not_found_message: str = MARKDOWN_NOT_FOUND_ERROR) -> bool:
        """Send a 404 response and return False when the Markdown file is missing."""
        if file_path.is_file():
            return True
        self._send_json(404, {"error": not_found_message})
        return False

    def _resolve_existing_markdown_path(self, requested_path: str, *, not_found_message: str = MARKDOWN_NOT_FOUND_ERROR) -> Path | None:
        """Resolve a Markdown path, sending a 404 response and returning None when missing."""
        file_path = self._resolve_markdown_path(requested_path)
        if not self._require_markdown_file(file_path, not_found_message):
            return None
        return file_path

    def _resolve_requested_markdown_path(self, parsed) -> Path | None:
        """Resolve the ``path`` query parameter to an existing Markdown file.

        Sends the 400/404 response and returns None when the request is invalid
        or the file is missing.
        """
        paths = parse_qs(parsed.query).get("path", [])
        if len(paths) != 1 or not paths[0]:
            self._send_json(400, {"error": "Expected a path parameter"})
            return None

        try:
            return self._resolve_existing_markdown_path(paths[0])
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return None

    def _notify_recipe_saved(self, file_path: Path, failure_message: str, **extra_fields) -> bool:
        """Notify listeners that a recipe was saved.

        Sends a 500 response built from ``failure_message`` (plus any extra
        fields) and returns False when the callback raises; returns True otherwise.
        """
        try:
            self._notify_markdown_saved(file_path)
        except Exception:
            logger.exception(f"Failed to regenerate recipe after saving {file_path}")
            self._send_json(500, {"error": failure_message, **extra_fields})
            return False
        return True

    # ----- GET handlers ----------------------------------------------------

    def _handle_health(self) -> None:
        self._send_json(200, {"status": "ok"})

    # ----- GET handlers: optional authentication ----------------------------

    def _auth_available(self) -> bool:
        return self.auth is not None and self.auth.enabled

    def _secure_cookies(self) -> bool:
        return bool(self.auth and self.auth.settings.secure_cookies)

    def _handle_auth_status(self) -> None:
        if not self._auth_available():
            self._send_json(
                200,
                {
                    "enabled": False,
                    "authenticated": False,
                    "permission": "edit",
                    "canEdit": True,
                    "isOwner": False,
                    "name": None,
                    "csrfToken": None,
                    "loginUrl": "/api/auth/login",
                    "logoutUrl": "/api/auth/logout",
                    "callbackPath": "/api/auth/callback",
                },
            )
            return
        self._send_json(200, self.auth.status(self._identity))

    def _handle_auth_login(self) -> None:
        if not self._auth_available():
            self.send_error(404, "Unknown API endpoint")
            return
        query = parse_qs(urlsplit(self.path).query)
        next_values = query.get("next", [])
        try:
            location, cookie = self.auth.begin_login(next_values[0] if next_values else "/")
        except OIDCError as exc:
            logger.warning(f"Unable to start OIDC login: {exc.detail or exc.message}")
            self._send_auth_error(503, "Sign-in unavailable", "Sign-in is temporarily unavailable.")
            return
        self._queue_cookie(FLOW_COOKIE, cookie, FLOW_TTL_SECONDS)
        self._redirect_to(location)

    def _handle_auth_callback(self) -> None:
        if not self._auth_available():
            self.send_error(404, "Unknown API endpoint")
            return
        params = parse_qs(urlsplit(self.path).query)
        flow_cookie = parse_cookies(self.headers.get("Cookie")).get(FLOW_COOKIE)
        # The flow cookie is single-use: clear it even when the callback fails.
        self._pending_headers.append(("Set-Cookie", clear_cookie_header(FLOW_COOKIE, secure=self._secure_cookies())))
        try:
            _session, cookie, return_to = self.auth.finish_login(params, flow_cookie)
        except OIDCError as exc:
            logger.warning(f"OIDC login failed: {exc.detail or exc.message}")
            self._send_auth_error(400, "Sign-in failed", exc.message)
            return
        self._queue_cookie(SESSION_COOKIE, cookie, self.auth.settings.session_lifetime_minutes * 60)
        self._redirect_to(return_to)

    def _handle_auth_settings_get(self) -> None:
        if not self._auth_available():
            self.send_error(404, "Unknown API endpoint")
            return
        self._send_json(200, self.auth.access.to_json())

    def _handle_auth_settings_post(self) -> None:
        if not self._auth_available():
            self.send_error(404, "Unknown API endpoint")
            return
        try:
            payload = self._read_json_payload()
            guest = Permission.parse(str(payload.get("guest", "")))
            authenticated = Permission.parse(str(payload.get("authenticated", "")))
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return
        self.auth.update_access(guest, authenticated)
        self._send_json(200, {"success": True, **self.auth.access.to_json()})

    def _handle_ai_status(self) -> None:
        logger.debug("Received /api/ai-status request")
        try:
            status = ai_recipe.ai_status(self.config)
        except Exception:
            logger.exception("Failed to check local model status")
            self._send_json(500, {"error": "Unable to check local model status"})
            return

        # The browser needs this to decide whether the AI bubble is
        # long-pressable for dictation.
        status["dictation_enabled"] = self._dictation_enabled()
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
                    "models": self._probe_configured_models(),
                },
            )
        except ValueError as exc:
            self._send_json(500, {"error": str(exc)})
        except Exception:
            logger.exception("Failed to read configuration")
            self._send_json(500, {"error": "Unable to read configuration"})

    def _probe_configured_models(self) -> dict:
        """Probe the three configured models' installation metadata.

        Best-effort: reports each model's on-disk size and whether it can be
        kept loaded, so the Configuration dialog can show the model size and
        disable the keep-alive setting when the model cannot be resident.
        Never raises; per-model failures are reported in the probe result.
        """
        config = self.config
        if config is None:
            return {}
        ai_endpoint = getattr(config, "model_endpoint", "") or ""
        transcription_endpoint = getattr(config, "transcription_endpoint", "") or DEFAULT_TRANSCRIPTION_ENDPOINT
        return {
            "all_purpose_model_name": ai_recipe.model_info(ai_endpoint, getattr(config, "all_purpose_model_name", "")),
            "image_analysis_model": ai_recipe.model_info(ai_endpoint, getattr(config, "image_analysis_model", "")),
            "transcription_model": ai_recipe.model_info(transcription_endpoint, getattr(config, "transcription_model", "")),
        }

    def _handle_recipe_folders_get(self) -> None:
        try:
            self._send_json(200, {"folders": self._list_recipe_folders()})
        except OSError:
            logger.exception("Failed to list recipe folders")
            self._send_json(500, {"error": "Unable to list recipe folders"})

    def _handle_metadata_options(self) -> None:
        """Return the metadata values already used across the recipe library."""
        try:
            options = collect_metadata_options(self.source_directory)
        except OSError:
            logger.exception("Failed to collect metadata options")
            self._send_json(500, {"error": "Unable to collect metadata options"})
            return

        self._send_json(200, {"options": options})

    def _handle_markdown_read(self, parsed) -> None:
        file_path = self._resolve_requested_markdown_path(parsed)
        if file_path is None:
            return

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read Markdown file")
            self._send_json(500, {"error": "Unable to read Markdown file"})
            return

        self._send_bytes(200, content.encode("utf-8"), "text/markdown; charset=utf-8")

    def _handle_recipe_editor_read(self, parsed) -> None:
        file_path = self._resolve_requested_markdown_path(parsed)
        if file_path is None:
            return

        self._handle_recipe_editor_get(file_path)

    def _handle_metadata_read(self, parsed) -> None:
        file_path = self._resolve_requested_markdown_path(parsed)
        if file_path is None:
            return

        self._handle_metadata_get(parsed.path, file_path)

    def _handle_metadata_get(self, path: str, file_path: Path) -> None:
        field_name = _metadata_field_name(path)
        if field_name is None:
            self._send_json(400, {"error": "Expected a metadata field name"})
            return

        try:
            recipe_post = _read_recipe_post(file_path)
        except Exception:
            logger.exception(f"Failed to parse YAML front matter for field {field_name}")
            self._send_json(500, {"error": "Unable to parse YAML front matter"})
            return

        metadata = recipe_post.metadata
        if field_name in metadata:
            self._send_json(200, {"value": metadata[field_name]})
        elif field_name == CATEGORIES_FIELD and LEGACY_CATEGORY_FIELD in metadata:
            self._send_json(200, {"value": metadata[LEGACY_CATEGORY_FIELD]})
        elif field_name in ("comments", "ratings"):
            self._send_json(200, {"value": []})
        elif field_name == "archived":
            self._send_json(200, {"value": False})
        else:
            self._send_json(404, {"error": f"Metadata field '{field_name}' not found"})

    def _handle_recipe_editor_get(self, file_path: Path) -> None:
        try:
            recipe_post = _read_recipe_post(file_path)
        except Exception:
            logger.exception("Failed to parse YAML front matter")
            self._send_json(500, {"error": "Unable to parse YAML front matter"})
            return

        self._send_json(
            200,
            {
                "metadata": _editor_metadata(recipe_post.metadata),
                "content": recipe_post.content,
                "images": self._list_recipe_images(file_path),
            },
        )

    def _drop_site_image_copy(self, file_path: Path, image_name: str) -> None:
        """Remove the image's copy in the generated site, if any."""
        try:
            relative_dir = file_path.parent.relative_to(self.source_directory)
            stale = Path(self.directory).resolve() / relative_dir / image_name
            stale.unlink(missing_ok=True)
        except OSError:
            logger.warning(f"Unable to remove stale image copy for {image_name}")

    def _list_recipe_images(self, file_path: Path) -> list[dict]:
        """Return the images sitting next to a recipe Markdown file.

        Each entry carries the bare filename and a root-absolute URL that
        points at the copy in the generated site, which is what the editor
        page uses for thumbnails.
        """
        try:
            entries = sorted(file_path.parent.iterdir(), key=lambda item: item.name)
        except OSError:
            return []

        relative_dir = file_path.parent.relative_to(self.source_directory)
        segments = [*relative_dir.parts, "placeholder"]
        images = []
        for entry in entries:
            if not entry.is_file() or entry.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            segments[-1] = entry.name
            url = "/" + "/".join(quote(segment) for segment in segments)
            images.append({"name": entry.name, "url": url})
        return images

    def _handle_bulk_editor_get(self, parsed) -> None:
        try:
            raw_paths = _validate_bulk_paths(parse_qs(parsed.query).get("path", []))
            file_paths = [self._resolve_markdown_path(path) for path in raw_paths]
        except ValueError as exc:
            self._send_payload_error(exc)
            return

        recipes = []
        try:
            for raw_path, file_path in zip(raw_paths, file_paths):
                if not self._require_markdown_file(file_path, f"{MARKDOWN_NOT_FOUND_ERROR}: {raw_path}"):
                    return
                recipe_post = _read_recipe_post(file_path)
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

    def _handle_shopping_list_get(self, parsed) -> None:
        """Return the ingredients of each selected recipe for the shopping list."""
        try:
            raw_paths = _validate_bulk_paths(parse_qs(parsed.query).get("path", []))
            file_paths = [self._resolve_markdown_path(path) for path in raw_paths]
        except ValueError as exc:
            self._send_payload_error(exc)
            return

        recipes = []
        for raw_path, file_path in zip(raw_paths, file_paths):
            html_file = self._recipe_page_path(file_path)
            if not html_file.is_file():
                self._send_json(404, {"error": f"Recipe page not found: {raw_path}"})
                return

            try:
                html = html_file.read_text(encoding="utf-8")
            except OSError:
                logger.exception("Failed to read generated recipe page")
                self._send_json(500, {"error": "Unable to read the generated recipe page"})
                return

            recipes.append({"path": raw_path, "ingredients": scrape_ingredients(html)})

        self._send_json(200, {"recipes": recipes})

    def _recipe_page_path(self, markdown_path: Path) -> Path:
        """Return the generated page that belongs to a recipe Markdown file."""
        relative_path = markdown_path.relative_to(self.source_directory)
        return (Path(self.directory).resolve() / relative_path).with_suffix(".html")

    # ----- POST handlers: speech transcription -------------------------------

    def _request_is_secure(self) -> bool:
        """Report whether the request reached the server over HTTPS.

        The server itself only speaks plain HTTP, so the site is served over
        HTTPS through a local reverse proxy (or tunnel) that terminates TLS
        and forwards the request. Those proxies record the original protocol
        in the ``X-Forwarded-Proto`` (or ``Forwarded``) header. Trusting that
        header assumes the reverse proxy is the only direct client; the
        default bind address is ``0.0.0.0``, so deployments exposed beyond the
        machine should restrict ``server_bind_address`` to loopback or enable
        authentication.
        """
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "")
        if forwarded_proto:
            # The left-most value is the protocol the client used.
            return forwarded_proto.split(",")[0].strip().lower() == "https"

        for element in self.headers.get("Forwarded", "").split(";"):
            key, _, value = element.partition("=")
            if key.strip().lower() == "proto":
                return value.strip().strip('"').lower() == "https"

        return False

    def _dictation_enabled(self) -> bool:
        """Report whether dictation is enabled in the saved configuration."""
        return getattr(self.config, "dictation_enabled", True) if self.config is not None else True

    @staticmethod
    def _transcription_settings(config) -> dict:
        """Resolve the Ollama transcription settings for a request.

        Reads the live configuration, falling back to the documented defaults
        when the configuration is missing keys (or missing entirely, as in
        some tests).
        """
        return {
            "endpoint": getattr(config, "transcription_endpoint", "") or DEFAULT_TRANSCRIPTION_ENDPOINT,
            "model": getattr(config, "transcription_model", "") or DEFAULT_TRANSCRIPTION_MODEL,
            "keep_alive": getattr(config, "transcription_keep_alive", "") or DEFAULT_KEEP_ALIVE_MINUTES,
        }

    def _handle_transcription(self) -> None:
        """Transcribe a recorded audio clip into text."""
        if not self._dictation_enabled():
            self._send_json(403, {"error": "Dictation is disabled in the server configuration"})
            return

        if not self._request_is_secure():
            self._send_json(403, {"error": "Speech transcription requires an HTTPS connection"})
            return

        content_type = self.headers.get("Content-Type", "")
        mime_type = content_type.split(";")[0].strip().lower()
        suffix = TRANSCRIPTION_AUDIO_SUFFIXES.get(mime_type)
        if suffix is None:
            self._send_json(415, {"error": "Unsupported audio format"})
            return

        content_length = self.headers.get("Content-Length")
        try:
            length = int(content_length) if content_length is not None else 0
        except ValueError:
            length = 0

        if length <= 0:
            self._send_json(400, {"error": "Empty audio recording"})
            return

        if length > MAX_TRANSCRIPTION_SIZE:
            self._send_json(413, {"error": "Audio recording too large"})
            return

        audio = self.rfile.read(length)
        if len(audio) != length:
            self._send_json(400, {"error": "Incomplete audio recording"})
            return

        transcription = self._transcription_settings(self.config)
        try:
            text = transcriber.transcribe(audio, suffix=suffix, **transcription)
        except TranscriberUnavailable as exc:
            logger.warning(f"Speech transcription is unavailable: {exc}")
            self._send_json(503, {"error": str(exc)})
            return
        except TranscriptionError as exc:
            logger.warning(f"Unable to decode the speech recording: {exc}")
            self._send_json(400, {"error": str(exc)})
            return
        except ValueError as exc:
            logger.warning(f"Invalid speech transcription request: {exc}")
            self._send_json(400, {"error": str(exc)})
            return
        except Exception:
            logger.exception("Speech transcription failed")
            self._send_json(500, {"error": "Speech transcription failed"})
            return

        self._send_json(200, {"text": text})

    # ----- POST handlers: configuration and AI -----------------------------

    def _handle_auth_logout(self) -> None:
        """Clear the signed session cookie. Also requires a CSRF token."""
        if not self._auth_available():
            self._discard_request_body()
            self.send_error(404, "Unknown API endpoint")
            return
        # The browser posts "{}"; drain it before responding so keep-alive
        # stays in sync (see _discard_request_body).
        self._discard_request_body()
        if self._identity is not None and not self.auth.csrf_ok(self.headers, self._identity):
            self._send_json(403, {"error": "Invalid CSRF token"})
            return
        self._pending_headers.append(("Set-Cookie", clear_cookie_header(SESSION_COOKIE, secure=self._secure_cookies())))
        self._send_json(200, {"success": True})

    def _handle_config_update(self) -> None:
        try:
            payload = self._read_json_payload()
            if self.config is None:
                raise ValueError("Configuration is not available")
            changed = self.config.apply_config_values(payload.get("values"))
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
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

    def _handle_test_transcription(self) -> None:
        """Verify the configured transcription server and model actually work.

        Sends the bundled speech sample ("Add two cups of flour and one cup
        of sugar.") through the same code path the dictation button uses.
        The Configuration dialog posts its unsaved transcription field values
        in the request body; anything absent falls back to the saved
        configuration.
        """
        try:
            payload = self._read_json_payload()
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        saved = self._transcription_settings(self.config)

        def pick(key: str, fallback: str) -> str:
            value = payload.get(key)
            return str(value).strip() if value is not None else fallback

        try:
            settings = {
                "endpoint": _validate_transcription_endpoint(pick("endpoint", saved["endpoint"]), "Transcription server"),
                "model": _validate_transcription_model(pick("model", saved["model"]), "Transcription model"),
                "keep_alive": _validate_keep_alive_minutes(pick("keep_alive", saved["keep_alive"]), "Transcription keep-alive"),
            }
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        try:
            sample = TRANSCRIPTION_TEST_SAMPLE_PATH.read_bytes()
        except OSError:
            logger.exception(f"The bundled transcription test sample is missing: {TRANSCRIPTION_TEST_SAMPLE_PATH}")
            self._send_json(500, {"error": "The bundled transcription test sample is missing"})
            return

        started = time.monotonic()
        try:
            text = transcriber.transcribe(sample, suffix=".wav", **settings)
        except TranscriberUnavailable as exc:
            logger.warning(f"Transcription test failed: {exc}")
            self._send_json(503, {"error": str(exc)})
            return
        except Exception:
            logger.exception("Transcription test failed")
            self._send_json(500, {"error": "Transcription test failed"})
            return

        seconds = round(time.monotonic() - started, 2)
        logger.info(f"Transcription test succeeded (endpoint={settings['endpoint']}, model={settings['model']}): {text!r}")
        self._send_json(200, {"ok": True, "text": text, "seconds": seconds})

    def _handle_ai_recipe(self) -> None:
        try:
            request = self._validate_ai_recipe_request()
        except (_RequestTooLarge, ValueError) as exc:
            logger.warning(f"Invalid AI recipe request: {exc}")
            self._send_payload_error(exc)
            return

        if request["stream_progress"]:
            self._stream_ai_recipe(request)
        else:
            self._run_ai_recipe(request)

    def _validate_ai_recipe_request(self) -> dict:
        payload, images = self._read_ai_recipe_payload()
        input_type = payload.get("inputType")
        input_value = payload.get("input")

        if input_type not in {"url", "text", "image"}:
            raise ValueError("Expected inputType to be 'url', 'text', or 'image'")

        if input_type == "image":
            if not images:
                raise ValueError("Expected at least one recipe image upload")
            images = self._validate_uploaded_images(images)
            for filename, _content in images:
                if Path(filename).suffix.lower() not in ai_recipe.IMAGE_MIME_TYPES:
                    raise ValueError(f"Unsupported image type for AI generation: {filename}. Use a JPG, PNG, GIF, WebP, BMP, or TIFF image.")
            filenames = ", ".join(filename for filename, _content in images)
            logger.info(f"Received AI recipe request from {len(images)} image input(s) ({filenames})")
            input_value = ""
        else:
            if not isinstance(input_value, str) or not input_value.strip():
                raise ValueError("Expected a non-empty input value")
            if images:
                raise ValueError("Unexpected uploaded file for this inputType")
            input_value = input_value.strip()
            logger.info(f"Received AI recipe request from {input_type} input ({len(input_value)} characters)")

        return {
            "input_type": input_type,
            "input_value": input_value,
            "images": images,
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
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

        def send_event(event: dict) -> None:
            event_type = str(event.get("type", "message")).replace("\n", "")
            body = json.dumps(event, default=json_default).encode("utf-8")
            try:
                self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
                self.wfile.write(b"data: " + body + b"\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise _StreamClosed from exc

        try:
            result = self._generate_ai_recipe(request, event_callback=send_event)
        except _StreamClosed:
            logger.debug("AI progress stream closed by the browser")
            return
        except (ai_recipe.ModelUnavailable, ai_recipe.ModelRequestError, ai_recipe.SourceFetchError, ValueError) as exc:
            logger.warning(f"AI recipe generation failed: {exc}")
            try:
                send_event({"type": ai_recipe.EVENT_ERROR, "state": ai_recipe.STATUS_ERROR, "message": str(exc)})
            except _StreamClosed:
                pass
        except Exception:
            logger.exception("Failed to generate a recipe with the local model")
            try:
                send_event({"type": ai_recipe.EVENT_ERROR, "state": ai_recipe.STATUS_ERROR, "message": "Unable to generate recipe"})
            except _StreamClosed:
                pass
        else:
            logger.info(f"AI recipe generation succeeded ({len(result.get('content', ''))} characters of Markdown)")
            try:
                send_event({"type": ai_recipe.EVENT_RESULT, "result": result})
            except _StreamClosed:
                logger.debug("AI result was not delivered because the browser closed the stream")

    def _generate_ai_recipe(self, request: dict, event_callback=None):
        if request["input_type"] == "image" and request["images"]:
            return ai_recipe.generate_recipe(
                self.config,
                request["input_type"],
                request["input_value"],
                event_callback=event_callback,
                images=request["images"],
            )
        return ai_recipe.generate_recipe(
            self.config,
            request["input_type"],
            request["input_value"],
            event_callback=event_callback,
        )

    # ----- POST handlers: the AI assistant ----------------------------------
    # The assistant (assets/ai-assistant/) answers free-form questions and may
    # rewrite the recipe the user is viewing. It never creates, deletes, or
    # edits any other recipe: the update tool it is given has no path
    # argument and is only offered when the request carries one.

    def _handle_ai_assistant(self) -> None:
        try:
            request = self._validate_ai_assistant_request()
        except (_RequestTooLarge, ValueError) as exc:
            logger.warning(f"Invalid AI assistant request: {exc}")
            self._send_payload_error(exc)
            return
        if request is None:
            # The response was already sent (a missing recipe answers 404).
            return

        if request["stream"]:
            self._stream_ai_assistant(request)
        else:
            self._run_ai_assistant(request)

    def _validate_ai_assistant_request(self) -> dict | None:
        payload = self._read_json_payload()
        message = ai_assistant.sanitize_message(payload.get("message"))
        history = ai_assistant.sanitize_history(payload.get("history"))

        current_file = None
        current_path_display = None
        raw_path = payload.get("path")
        if raw_path is not None:
            if not isinstance(raw_path, str):
                raise ValueError("Expected a string path parameter")
            current_file = self._resolve_markdown_path(raw_path)
            if not self._require_markdown_file(current_file):
                return None
            current_path_display = display_path(self.source_directory, current_file)
            logger.info(f"AI assistant request for {current_path_display}")

        return {
            "message": message,
            "history": history,
            "current_file": current_file,
            "current_path_display": current_path_display,
            "stream": payload.get("stream") is True,
        }

    def _make_assistant_edit(self, file_path: Path) -> Callable[[str, dict], str]:
        """Return the edit callback bound to the one recipe being viewed.

        The assistant tool calls this with the replacement body (and any
        metadata fields to change); there is intentionally no way for the
        model to address another file.
        """

        def apply_edit(content: str, metadata: dict) -> str:
            validated = _validate_assistant_metadata(metadata)
            try:
                recipe_post = _read_recipe_post(file_path)
                _apply_editor_metadata(recipe_post.metadata, validated)
                _drop_legacy_category(recipe_post.metadata)
                recipe_post.metadata["updatedOn"] = _now_utc_iso()
                recipe_post.content = content
                self._write_recipe_post_with_images(file_path, recipe_post, [], exclusive=False)
            except (OSError, recipe_history.HistoryError) as exc:
                logger.exception(f"The assistant could not save {file_path}")
                raise ValueError("Unable to save the recipe file") from exc

            logger.info(f"Saved recipe assistant edit: {file_path}")
            try:
                self._notify_markdown_saved(file_path)
            except Exception:
                logger.exception(f"The assistant edited {file_path} but HTML regeneration failed")
                return "The recipe was saved, but regenerating it failed; the page may be stale until the next rebuild."
            return f"Saved {display_path(self.source_directory, file_path)} and regenerated the page."

        return apply_edit

    def _generate_ai_assistant(self, request: dict, event_callback=None):
        apply_edit = self._make_assistant_edit(request["current_file"]) if request["current_file"] is not None else None
        return ai_assistant.run_assistant(
            self.config,
            request["message"],
            request["history"],
            source_directory=self.source_directory,
            current_file=request["current_file"],
            current_path_display=request["current_path_display"],
            apply_edit=apply_edit,
            event_callback=event_callback,
        )

    def _run_ai_assistant(self, request: dict) -> None:
        try:
            result = self._generate_ai_assistant(request)
        except ai_recipe.ModelUnavailable as exc:
            logger.warning(f"AI assistant model unavailable: {exc}")
            self._send_json(503, {"error": str(exc)})
        except ai_recipe.ModelRequestError as exc:
            logger.warning(f"AI assistant request failed: {exc}")
            self._send_json(502, {"error": str(exc)})
        except ValueError as exc:
            logger.warning(f"Invalid AI assistant input: {exc}")
            self._send_json(400, {"error": str(exc)})
        except Exception:
            logger.exception("Failed to run the AI assistant")
            self._send_json(500, {"error": "Unable to run the assistant"})
        else:
            self._send_json(200, result)

    def _stream_ai_assistant(self, request: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

        def send_event(event: dict) -> None:
            event_type = str(event.get("type", "message")).replace("\n", "")
            body = json.dumps(event, default=json_default).encode("utf-8")
            try:
                self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
                self.wfile.write(b"data: " + body + b"\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise _StreamClosed from exc

        try:
            result = self._generate_ai_assistant(request, event_callback=send_event)
        except _StreamClosed:
            logger.debug("AI assistant stream closed by the browser")
            return
        except (ai_recipe.ModelUnavailable, ai_recipe.ModelRequestError, ValueError) as exc:
            logger.warning(f"AI assistant failed: {exc}")
            try:
                send_event({"type": ai_assistant.EVENT_ERROR, "state": ai_assistant.STATUS_ERROR, "message": str(exc)})
            except _StreamClosed:
                pass
        except Exception:
            logger.exception("Failed to run the AI assistant")
            try:
                send_event({"type": ai_assistant.EVENT_ERROR, "state": ai_assistant.STATUS_ERROR, "message": "Unable to run the assistant"})
            except _StreamClosed:
                pass
        else:
            logger.info(f"AI assistant replied ({len(result.get('reply', ''))} characters, edited={result.get('edited')})")
            try:
                send_event({"type": ai_assistant.EVENT_RESULT, "result": result})
            except _StreamClosed:
                logger.debug("AI assistant result was not delivered because the browser closed the stream")

    # ----- POST handlers: the assistant's Markdown rendering -----------------
    # The chat renders both the user's and the assistant's messages as
    # Markdown with the same strategy the recipe pages use (see
    # assistant_render.py); the fragment is sanitized server-side.

    def _handle_assistant_markdown(self) -> None:
        try:
            payload = self._read_json_payload()
            markdown_text = payload.get("markdown")
            if not isinstance(markdown_text, str) or not markdown_text.strip():
                raise ValueError("Expected a non-empty markdown string")
            if len(markdown_text) > assistant_render.MAX_RENDER_CHARS:
                raise ValueError(f"The Markdown is too long (at most {assistant_render.MAX_RENDER_CHARS} characters)")
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        try:
            html = assistant_render.render_chat_markdown(markdown_text)
        except Exception:
            logger.exception("Failed to render the assistant Markdown")
            self._send_json(500, {"error": "Unable to render the message"})
            return
        self._send_json(200, {"html": html})

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
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        self._create_recipe(folder_path, folder, create_folder, content, metadata, images)

    def _create_recipe(self, folder_path: Path, folder: str, create_folder: bool, content: str, metadata: dict, images) -> None:
        try:
            folder_path = self._prepare_recipe_folder(folder_path, folder, create_folder, content, metadata)
            if folder_path is None:
                return

            file_path = folder_path / RECIPE_FILENAME
            if file_path.exists():
                self._send_json(409, {"error": "A recipe already exists in that folder"})
                return

            recipe_post = frontmatter.Post(content, **self._metadata_for_new_recipe(metadata))
            self._write_recipe_post_with_images(file_path, recipe_post, images, exclusive=True)

            logger.info(f"Created recipe: {file_path}")
            if not self._notify_recipe_saved(file_path, "Recipe created, but HTML regeneration failed"):
                return
            self._send_json(201, {"success": True, "path": file_path.relative_to(self.source_directory).as_posix()})
        except FileExistsError:
            self._send_json(409, {"error": "A recipe or folder already exists at that location"})
        except OSError:
            logger.exception("Failed to create recipe")
            self._send_json(500, {"error": "Unable to create recipe"})
        except Exception:
            logger.exception("Recipe created, but HTML regeneration failed")
            self._send_json(500, {"error": "Recipe created, but HTML regeneration failed"})

    def _prepare_recipe_folder(self, folder_path: Path, folder: str, create_folder: bool, content: str, metadata: dict) -> Path | None:
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
        recipe_metadata["updatedOn"] = _now_utc_iso()
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
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        self._save_recipe_editor(file_path, content, metadata, images)

    def _save_recipe_editor(self, file_path: Path, content: str, metadata: dict, images) -> None:
        try:
            if not self._require_markdown_file(file_path):
                return

            recipe_post = _read_recipe_post(file_path)
            _apply_editor_metadata(recipe_post.metadata, metadata)
            _drop_legacy_category(recipe_post.metadata)
            recipe_post.metadata["updatedOn"] = _now_utc_iso()
            recipe_post.content = content

            changed = self._write_recipe_post_with_images(file_path, recipe_post, images, exclusive=False)
            logger.info(f"Saved recipe editor content: {file_path}")
            if (changed or images) and not self._notify_recipe_saved(file_path, "Recipe saved, but HTML regeneration failed"):
                return
            self._send_json(200, {"success": True})
        except FileExistsError as exc:
            self._send_json(409, {"error": str(exc)})
        except recipe_history.HistoryError:
            logger.exception("Failed to snapshot the recipe before saving")
            self._send_json(500, {"error": "Unable to save the recipe history; the recipe was not changed"})
        except OSError:
            logger.exception("Failed to save recipe")
            self._send_json(500, {"error": "Unable to save recipe"})
        except Exception:
            logger.exception("Failed to save or regenerate recipe HTML")
            self._send_json(500, {"error": "Recipe saved, but HTML regeneration failed"})

    def _write_recipe_post_with_images(self, file_path: Path, recipe_post, images, *, exclusive: bool) -> bool:
        """Save the recipe and its staged images.

        Returns True when the recipe file was written. Raises
        :class:`recipe_history.HistoryError` when the previous version cannot be
        snapshotted; in that case the recipe is left untouched and no staged
        images are kept.
        """
        written_images = self._write_uploaded_images(file_path.parent, images)
        try:
            return _save_recipe_contents(file_path, frontmatter.dumps(recipe_post), exclusive=exclusive)
        except Exception:
            self._remove_uploaded_images(written_images)
            raise

    def _handle_recipe_images_rename_post(self) -> None:
        """Rename one of the images that sit next to a recipe Markdown file.

        The Markdown on disk is rewritten so references to the old filename
        point at the new one, the stale copy in the generated site is dropped,
        and the recipe is regenerated so the hero and index stay in sync.
        """
        try:
            payload = self._read_json_payload()
            path = payload.get("path")
            from_name = payload.get("from")
            to_name = payload.get("to")
            if not isinstance(path, str) or not isinstance(from_name, str) or not isinstance(to_name, str):
                raise ValueError("Expected string fields: path, from, to")
            file_path = self._resolve_existing_markdown_path(path)
            if file_path is None:
                return
            source_name = _validate_image_name(from_name, field="from")
            target_name = _validate_image_name(to_name, field="to")
            if source_name == target_name:
                raise ValueError("Enter a different name to rename the image")
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        directory = file_path.parent
        source_path = directory / source_name
        target_path = directory / target_name
        if not source_path.is_file():
            self._send_json(404, {"error": f"Image not found: {source_name}"})
            return
        same_name = source_name.casefold() == target_name.casefold()
        if not same_name and target_path.exists():
            self._send_json(409, {"error": f"An image named {target_name} already exists"})
            return

        try:
            source_path.rename(target_path)
        except OSError:
            logger.exception(f"Failed to rename image {source_path} to {target_path}")
            self._send_json(500, {"error": "Unable to rename image"})
            return

        try:
            content = file_path.read_text(encoding="utf-8")
            updated = _replace_image_reference(content, source_name, target_name)
            if updated != content:
                _save_recipe_contents(file_path, updated)
        except recipe_history.HistoryError:
            logger.exception("Failed to snapshot the recipe before updating the image references")
            try:
                target_path.rename(source_path)
            except OSError:
                logger.exception(f"Failed to roll back image rename of {target_path}")
            self._send_json(500, {"error": "Unable to update the recipe history; the image was not renamed"})
            return
        except OSError:
            # Best-effort rollback so the Markdown never points at a missing file.
            try:
                target_path.rename(source_path)
            except OSError:
                logger.exception(f"Failed to roll back image rename of {target_path}")
            logger.exception(f"Failed to update Markdown references after renaming {source_path}")
            self._send_json(500, {"error": "Unable to update Markdown references; the image was not renamed"})
            return

        # Drop the stale copy in the generated site so the old URL stops working.
        self._drop_site_image_copy(file_path, source_name)

        logger.info(f"Renamed image {source_name} to {target_name} for {file_path}")
        if not self._notify_recipe_saved(
            file_path,
            "Image renamed, but HTML regeneration failed",
            images=self._list_recipe_images(file_path),
        ):
            return

        self._send_json(200, {"success": True, "images": self._list_recipe_images(file_path)})

    def _handle_recipe_images_upload_post(self) -> None:
        """Save staged images into the recipe folder without saving the recipe.

        Lets the editor upload an image as soon as it is staged; the recipe
        Markdown is untouched, and the response carries the refreshed folder
        listing so the UI can update in place.
        """
        try:
            payload, images = self._read_recipe_payload()
            path = payload.get("path")
            if not isinstance(path, str):
                raise ValueError("Expected string field: path")
            images = self._validate_uploaded_images(images)
            if not images:
                raise ValueError("Choose at least one image to upload")
            file_path = self._resolve_existing_markdown_path(path)
            if file_path is None:
                return
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        try:
            self._write_uploaded_images(file_path.parent, images)
        except FileExistsError as exc:
            self._send_json(409, {"error": str(exc)})
            return
        except OSError:
            logger.exception(f"Failed to save uploaded images for {file_path}")
            self._send_json(500, {"error": "Unable to save image"})
            return

        logger.info(f"Uploaded {len(images)} image(s) for {file_path}")
        if not self._notify_recipe_saved(
            file_path,
            "Image uploaded, but HTML regeneration failed",
            images=self._list_recipe_images(file_path),
        ):
            return

        self._send_json(200, {"success": True, "images": self._list_recipe_images(file_path)})

    def _handle_recipe_images_delete_post(self) -> None:
        """Delete one of the images that sit next to a recipe Markdown file.

        The image is removed from the folder and from the generated site.
        The Markdown is left alone; when it references the image the response
        says so so the editor can warn the user.
        """
        try:
            payload = self._read_json_payload()
            path = payload.get("path")
            name = payload.get("name")
            if not isinstance(path, str) or not isinstance(name, str):
                raise ValueError("Expected string fields: path, name")
            file_path = self._resolve_existing_markdown_path(path)
            if file_path is None:
                return
            image_name = _validate_image_name(name, field="name")
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        target = file_path.parent / image_name
        if not target.is_file():
            self._send_json(404, {"error": f"Image not found: {image_name}"})
            return

        try:
            content = file_path.read_text(encoding="utf-8")
            referenced = bool(_image_name_pattern(image_name).search(content))
            quoted_name = quote(image_name)
            if not referenced and quoted_name != image_name:
                referenced = bool(_image_name_pattern(quoted_name).search(content))
            target.unlink()
        except OSError:
            logger.exception(f"Failed to delete image {target}")
            self._send_json(500, {"error": "Unable to delete image"})
            return

        # Check the main image is still available; fall back to the first
        # image in the folder alphabetically when the deleted file was it.
        try:
            remaining = [image["name"] for image in self._list_recipe_images(file_path)]
            updated, fallback_target = _fallback_main_image(content, image_name, remaining)
            if updated is not None and updated != content:
                _save_recipe_contents(file_path, updated)
                logger.info(f"Main image fell back to {fallback_target if fallback_target else 'nothing (image link removed)'}")
        except recipe_history.HistoryError:
            logger.exception("Failed to snapshot the recipe before updating the main image")
            self._send_json(
                500,
                {
                    "error": "Image deleted, but the Markdown could not be updated",
                    "images": self._list_recipe_images(file_path),
                    "referenced": referenced,
                },
            )
            return
        except OSError:
            logger.exception(f"Failed to update the Markdown after deleting {target}")
            self._send_json(
                500,
                {
                    "error": "Image deleted, but the Markdown could not be updated",
                    "images": self._list_recipe_images(file_path),
                    "referenced": referenced,
                },
            )
            return

        self._drop_site_image_copy(file_path, image_name)
        logger.info(f"Deleted image {image_name} for {file_path}")
        if not self._notify_recipe_saved(
            file_path,
            "Image deleted, but HTML regeneration failed",
            images=self._list_recipe_images(file_path),
            referenced=referenced,
        ):
            return

        self._send_json(200, {"success": True, "images": self._list_recipe_images(file_path), "referenced": referenced})

    def _handle_metadata_post(self, path: str) -> None:
        field_name = _metadata_field_name(path)
        if field_name is None:
            self._send_json(400, {"error": "Expected a metadata field name"})
            return

        try:
            payload = self._read_json_payload()
            recipe_path = payload.get("path")
            value = payload.get("value")
            if not isinstance(recipe_path, str):
                raise ValueError("Expected string field: path")

            if field_name == "ratings":
                value = _validate_ratings(value)
            elif field_name in EDITOR_METADATA_FIELDS:
                if value is not None:
                    value = _validate_editor_field(field_name, EDITOR_METADATA_FIELDS[field_name], value)

            file_path = self._resolve_markdown_path(recipe_path)
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        self._save_metadata_field(file_path, field_name, value)

    def _save_metadata_field(self, file_path: Path, field_name: str, value) -> None:
        try:
            if not self._require_markdown_file(file_path):
                return

            def mutate(post: frontmatter.Post) -> None:
                metadata = post.metadata
                if value is not None:
                    metadata[field_name] = value
                else:
                    metadata.pop(field_name, None)
                if field_name == CATEGORIES_FIELD:
                    _drop_legacy_category(metadata)

            _, changed = _update_recipe_post(file_path, mutate)
            logger.info(f"Updated metadata field '{field_name}' in file: {file_path}")

            if changed and not self._notify_recipe_saved(file_path, "Metadata saved, but recipe regeneration failed"):
                return

            self._send_json(200, {"success": True, "field": field_name})
        except recipe_history.HistoryError:
            logger.exception("Failed to snapshot the recipe before saving")
            self._send_json(500, {"error": "Unable to save the recipe history; the recipe was not changed"})
            return
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
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        try:
            if not self._require_markdown_file(file_path):
                return

            changed = _save_recipe_contents(file_path, content)
            logger.info(f"Saved Markdown file: {file_path}")
            if changed and not self._notify_recipe_saved(file_path, "Markdown saved, but HTML regeneration failed"):
                return
            self._send_json(200, {"success": True})
        except recipe_history.HistoryError:
            logger.exception("Failed to snapshot the recipe before saving")
            self._send_json(500, {"error": "Unable to save the recipe history; the recipe was not changed"})
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
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        # Pre-check every target before writing any of them.
        for raw_path, file_path in zip(raw_paths, file_paths):
            if not self._require_markdown_file(file_path, f"{MARKDOWN_NOT_FOUND_ERROR}: {raw_path}"):
                return

        try:
            changed_paths = self._apply_bulk_edit(file_paths, fields, metadata, rating_override)
        except recipe_history.HistoryError:
            logger.exception("Failed to snapshot a recipe before saving")
            self._send_json(500, {"error": "Unable to save the recipe history; no recipes were changed"})
            return
        except OSError:
            logger.exception("Failed to save bulk edit")
            self._send_json(500, {"error": "Unable to save recipes"})
            return
        except Exception:
            logger.exception("Failed to parse recipe for bulk edit")
            self._send_json(500, {"error": "Unable to parse recipe data"})
            return

        for file_path in changed_paths:
            if not self._notify_recipe_saved(file_path, "Recipes saved, but HTML regeneration failed"):
                return

        self._send_json(200, {"success": True, "paths": raw_paths, "count": len(raw_paths)})

    @staticmethod
    def _apply_bulk_edit(file_paths: list[Path], fields: list[str], metadata: dict, rating_override) -> list[Path]:
        changed_paths: list[Path] = []
        for file_path in file_paths:

            def mutate(post: frontmatter.Post) -> None:
                if metadata:
                    subset = {field: metadata.get(field) for field in fields}
                    _apply_editor_metadata(post.metadata, subset)
                    _drop_legacy_category(post.metadata)
                if rating_override is not None:
                    name, score = rating_override
                    post.metadata["ratings"] = _apply_rating_override(post.metadata.get("ratings"), name, score)
                if metadata or rating_override is not None:
                    post.metadata["updatedOn"] = _now_utc_iso()

            _, changed = _update_recipe_post(file_path, mutate)
            if changed:
                changed_paths.append(file_path)
                logger.info(f"Bulk-saved recipe: {file_path}")
        return changed_paths

    def _handle_bulk_delete(self) -> None:
        try:
            payload = self._read_json_payload()
            raw_paths = _validate_bulk_paths(payload.get("paths"))
            file_paths = [self._resolve_markdown_path(path) for path in raw_paths]
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        for raw_path, file_path in zip(raw_paths, file_paths):
            if not self._require_markdown_file(file_path, f"{MARKDOWN_NOT_FOUND_ERROR}: {raw_path}"):
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
            logger.info(f"Deleted recipe: {file_path}")
        return deleted

    # ----- DELETE handlers -------------------------------------------------

    def _handle_recipe_delete(self, parsed) -> None:
        file_path = self._resolve_requested_markdown_path(parsed)
        if file_path is None:
            return

        try:
            self._delete_recipe_files([file_path])
        except Exception:
            logger.exception("Failed to delete recipe")
            self._send_json(500, {"error": "Unable to delete recipe"})
            return

        if self.on_recipes_deleted is not None:
            try:
                self.on_recipes_deleted([file_path])
            except Exception:
                logger.exception("Recipe deleted, but index regeneration failed")
                self._send_json(500, {"error": "Recipe deleted, but index regeneration failed"})
                return
        self._send_json(200, {"success": True})

    # ----- history API -------------------------------------------------------
    # Snapshots of every RecipeServer-managed modification live in the
    # history directory (see ``history.py``); these endpoints let the
    # recipe page browse, preview, compare, and restore them.

    def _history_query(self, parsed) -> tuple[str | None, str | None, str | None]:
        query = parse_qs(parsed.query)

        def one(key: str) -> str | None:
            values = query.get(key, [])
            return values[0] if len(values) == 1 and values[0] else None

        return one("path"), one("snapshot"), one("recipeId")

    def _resolve_history_target(self, path: str | None, recipe_id: str | None) -> tuple[Path, str] | None:
        """Resolve the (file path, recipe_id) pair a history request addresses.

        An existing recipe keeps its own identity (a missing identifier is
        assigned in place, without a snapshot). A deleted recipe has no file;
        its ``recipe_id`` must then be supplied by the caller.
        """
        if path is None:
            self._send_json(400, {"error": "Expected a path parameter"})
            return None
        try:
            file_path = self._resolve_markdown_path(path)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return None

        if file_path.is_file():
            resolved_id = self._ensure_recipe_id(file_path)
            if resolved_id is None:
                return None
            return file_path, resolved_id

        candidate = (recipe_id or "").strip()
        if not candidate:
            self._send_json(404, {"error": MARKDOWN_NOT_FOUND_ERROR})
            return None
        if not is_valid_recipe_id(candidate):
            self._send_json(400, {"error": "Expected a valid recipeId"})
            return None
        return file_path, canonical_recipe_id(candidate)

    def _ensure_recipe_id(self, file_path: Path) -> str | None:
        """Return the recipe's ``recipe_id``, assigning one in place when missing."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception(f"Failed to read {file_path}")
            self._send_json(500, {"error": "Unable to read the recipe file"})
            return None

        recipe_id = extract_recipe_id(content)
        if recipe_id is not None:
            return recipe_id

        recipe_id = new_recipe_id()
        try:
            # Identity assignment is not a content modification, so it creates
            # no history snapshot.
            recipe_history.write_file_atomic(file_path, set_recipe_id(content, recipe_id))
            logger.info(f"Assigned recipe_id to {file_path}")
        except OSError:
            logger.exception(f"Unable to assign a recipe_id to {file_path}")
            self._send_json(500, {"error": "Unable to assign the recipe an identity"})
            return None
        return recipe_id

    @staticmethod
    def _snapshot_payload(recipe_id: str) -> list[dict]:
        return [
            {
                "id": snapshot.id,
                "created": snapshot.created.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "size": snapshot.size,
            }
            for snapshot in recipe_history.list_snapshots(recipe_id)
        ]

    def _history_snapshot_for(self, recipe_id: str, snapshot_id: str | None) -> str | None:
        """Read a snapshot, sending the error response and returning None on failure."""
        if snapshot_id is None:
            self._send_json(400, {"error": "Expected a snapshot parameter"})
            return None
        if not recipe_history.is_valid_snapshot_id(snapshot_id):
            self._send_json(400, {"error": "Expected a valid snapshot"})
            return None
        try:
            return recipe_history.read_snapshot(recipe_id, snapshot_id)
        except FileNotFoundError:
            self._send_json(404, {"error": "Snapshot not found"})
            return None
        except recipe_history.HistoryError:
            self._send_json(400, {"error": "Expected a valid snapshot"})
            return None

    def _handle_history_list(self, parsed) -> None:
        path, _, recipe_id_param = self._history_query(parsed)
        target = self._resolve_history_target(path, recipe_id_param)
        if target is None:
            return
        file_path, recipe_id = target

        payload = {"path": path, "recipeId": recipe_id, "snapshots": self._snapshot_payload(recipe_id)}
        self._send_json(200, payload)

    def _handle_history_preview(self, parsed) -> None:
        path, snapshot_id, recipe_id_param = self._history_query(parsed)
        target = self._resolve_history_target(path, recipe_id_param)
        if target is None:
            return
        file_path, recipe_id = target
        content = self._history_snapshot_for(recipe_id, snapshot_id)
        if content is None:
            return

        try:
            rendered = self._render_history_preview(content, file_path)
        except Exception:
            logger.exception("Failed to render the historical preview")
            self._send_json(500, {"error": "Unable to render the historical version"})
            return
        self._send_bytes(200, rendered.encode("utf-8"), "text/html; charset=utf-8")

    def _render_history_preview(self, snapshot_content: str, current_recipe: Path | None) -> str:
        """Render *snapshot_content* through the recipe pipeline, scripts stripped.

        The snapshot is converted in a scratch directory, so the current
        recipe is never touched. The current recipe's images are copied into
        the scratch directory (so the hero image and accent color resolve like
        any other render) and inlined as data URIs in the output (so the
        preview frame is self-contained). The returned document is a full
        HTML page suitable for embedding in the history dialog's preview frame.
        """
        from types import SimpleNamespace

        from bs4 import BeautifulSoup

        from .markdown_to_html import MarkdownToHTMLConverter

        recipe_directory = current_recipe.parent if current_recipe is not None and current_recipe.is_file() else None

        with tempfile.TemporaryDirectory(prefix="recipeserver-history-preview-") as temp_dir:
            temp_path = Path(temp_dir)
            recipe_path = temp_path / RECIPE_FILENAME
            recipe_path.write_text(snapshot_content, encoding="utf-8")
            if recipe_directory is not None:
                for candidate in recipe_directory.iterdir():
                    if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
                        shutil.copy2(candidate, temp_path / candidate.name)
            html_path = temp_path / "recipe.html"
            preview_cfg = SimpleNamespace(source_directory=temp_path, site_directory=temp_path)
            MarkdownToHTMLConverter(preview_cfg).convert(recipe_path, html_path)
            rendered = html_path.read_text(encoding="utf-8")

        if recipe_directory is None:
            return _sanitize_preview_html(rendered)

        soup = BeautifulSoup(_sanitize_preview_html(rendered), "html.parser")
        for image in soup.find_all("img"):
            source = image.get("src")
            if not source or source.startswith(("http://", "https://", "data:", "/assets/")):
                continue
            name = unquote(source.split("?", 1)[0]).rsplit("/", 1)[-1]
            candidate = recipe_directory / name
            if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
                mime_type = guess_type(candidate.name)[0] or "application/octet-stream"
                encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
                image["src"] = f"data:{mime_type};base64,{encoded}"
        return str(soup)

    def _handle_history_compare(self, parsed) -> None:
        path, snapshot_id, recipe_id_param = self._history_query(parsed)
        target = self._resolve_history_target(path, recipe_id_param)
        if target is None:
            return
        file_path, recipe_id = target
        content = self._history_snapshot_for(recipe_id, snapshot_id)
        if content is None:
            return

        try:
            current = file_path.read_text(encoding="utf-8") if file_path.is_file() else ""
        except OSError:
            logger.exception(f"Failed to read the current recipe at {file_path}")
            self._send_json(500, {"error": "Unable to read the current recipe"})
            return

        diff = "\n".join(
            difflib.unified_diff(
                content.splitlines(),
                current.splitlines(),
                fromfile="snapshot",
                tofile="current",
                n=3,
                lineterm="",
            )
        )
        snapshot_info = next((snapshot for snapshot in recipe_history.list_snapshots(recipe_id) if snapshot.id == snapshot_id), None)
        created = snapshot_info.created.isoformat(timespec="milliseconds").replace("+00:00", "Z") if snapshot_info else None
        payload = {
            "path": path,
            "recipeId": recipe_id,
            "snapshot": {"id": snapshot_id, "created": created},
            "diff": diff,
        }
        self._send_json(200, payload)

    def _handle_history_restore(self) -> None:
        try:
            payload = self._read_json_payload()
            path = payload.get("path")
            snapshot_id = payload.get("snapshot")
            recipe_id_param = payload.get("recipeId")
            if not isinstance(path, str) or not isinstance(snapshot_id, str):
                raise ValueError("Expected string fields: path and snapshot")
        except (_RequestTooLarge, ValueError) as exc:
            self._send_payload_error(exc)
            return

        if not recipe_history.is_valid_snapshot_id(snapshot_id):
            self._send_json(400, {"error": "Expected a valid snapshot"})
            return
        target = self._resolve_history_target(path, recipe_id_param if isinstance(recipe_id_param, str) else None)
        if target is None:
            return
        file_path, recipe_id = target

        # Hold the per-recipe retention lock across the read and the write so
        # a background prune never removes the snapshot mid-restore (and the
        # pre-restore snapshot this save creates is safe too).
        with get_retention_manager().recipe_lock(recipe_id):
            content = self._history_snapshot_for(recipe_id, snapshot_id)
            if content is None:
                return

            try:
                # The common save mechanism snapshots the current recipe before
                # replacing it, so the restore is itself reversible.
                _save_recipe_contents(
                    file_path,
                    content,
                    force_recipe_id=recipe_id,
                    create_parents=not file_path.is_file(),
                )
            except recipe_history.HistoryError:
                logger.exception("Failed to snapshot the current recipe before restoring")
                self._send_json(500, {"error": "Unable to snapshot the current recipe; nothing was restored"})
                return
            except OSError:
                logger.exception(f"Failed to restore snapshot {snapshot_id} to {file_path}")
                self._send_json(500, {"error": "Unable to restore the recipe"})
                return

        logger.info(f"Restored snapshot {snapshot_id} to {file_path}")
        if not self._notify_recipe_saved(file_path, "Version restored, but HTML regeneration failed"):
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
        archive_path: Path | None = None
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
            if archive_path is not None:
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
        message = BytesParser(policy=default).parsebytes(b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        if not message.is_multipart():
            raise ValueError("Invalid multipart request")
        return message

    def _read_multipart_payload(self) -> tuple[dict, list[tuple[str, bytes]]]:
        """Read a multipart/form-data body into its text fields and file uploads."""
        content_type = self.headers.get("Content-Type", "")
        body = self._read_body(self.MAX_IMAGE_UPLOAD_SIZE, "Image upload request too large")
        message = self._parse_multipart_message(body, content_type)

        payload: dict = {}
        images: list[tuple[str, bytes]] = []
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

        return payload, images

    def _is_multipart_request(self) -> bool:
        return self.headers.get("Content-Type", "").lower().startswith("multipart/form-data")

    def _read_ai_recipe_payload(self) -> tuple[dict, list[tuple[str, bytes]]]:
        """Read an AI recipe request, which may carry multipart image uploads."""
        if not self._is_multipart_request():
            return self._read_json_payload(), []

        payload, images = self._read_multipart_payload()
        if "stream" in payload:
            if payload["stream"] not in {"true", "false"}:
                raise ValueError("Invalid stream value")
            payload["stream"] = payload["stream"] == "true"
        return payload, images

    def _read_recipe_payload(self) -> tuple[dict, list[tuple[str, bytes]]]:
        if not self._is_multipart_request():
            return self._read_json_payload(), []

        payload, images = self._read_multipart_payload()
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
            _validate_image_filename(filename)
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
        if _xml_local_name(root.tag) != "svg":
            raise ValueError(f"Invalid SVG image: {filename}")

        for element in root.iter():
            if _xml_local_name(element.tag) in _SVG_BLOCKED_TAGS:
                raise ValueError(f"SVG contains unsupported active content: {filename}")
            for attribute, value in element.attrib.items():
                _validate_svg_attribute(filename, attribute, value)

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
        return resolve_recipe_file(self.source_directory, requested_path)

    def _resolve_recipe_directory(self, requested_path: str) -> Path:
        return resolve_recipe_folder(self.source_directory, requested_path)

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
        if not (self.source_directory / RECIPE_FILENAME).exists():
            folders.append("")

        for folder in self.source_directory.rglob("*"):
            if folder.is_symlink() or not folder.is_dir():
                continue
            resolved_folder = folder.resolve()
            if not resolved_folder.is_relative_to(self.source_directory) or (resolved_folder / RECIPE_FILENAME).exists():
                continue
            folders.append(folder.relative_to(self.source_directory).as_posix())

        return sorted(folders, key=str.casefold)

    # ----- response helpers ------------------------------------------------

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, default=json_default).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


# The default socketserver listen backlog is 5. Windows answers a
# connection that arrives with a full backlog with an explicit reset
# (WSAECONNREFUSED) instead of silently dropping the SYN for the client to
# retransmit, as Linux and macOS do — so a burst of upstream connections
# from a reverse proxy (several connections per page load through an HTTPS
# terminator) surfaced as intermittent 502 Bad Gateway for the page's
# assets. 128 covers any browser's parallel-asset burst in the kernel
# instead of refusing the extra connections.
LISTEN_BACKLOG = 128


class _RecipeThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a listen backlog large enough for bursty clients."""

    request_queue_size = LISTEN_BACKLOG


class _ThreadingHTTPServerIPv6(_RecipeThreadingHTTPServer):
    """Listen-backlog-enlarged ThreadingHTTPServer that listens on IPv6 sockets."""

    address_family = socket.AF_INET6


class Server:
    def __init__(
        self,
        cfg: Configuration,
        on_markdown_saved: MarkdownSavedCallback | None = None,
        on_config_saved: ConfigSavedCallback | None = None,
        on_recipes_deleted: RecipesDeletedCallback | None = None,
        auth: AuthManager | None = None,
    ):
        self.cfg = cfg
        self.on_markdown_saved = on_markdown_saved
        self.on_config_saved = on_config_saved
        self.on_recipes_deleted = on_recipes_deleted
        self.auth = auth
        self._http_server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        """Configured listen port, falling back to the default."""
        return getattr(self.cfg, "server_port", DEFAULT_SERVER_PORT)

    @property
    def bind_address(self) -> str:
        """Configured bind address, falling back to the configured default."""
        return getattr(self.cfg, "server_bind_address", DEFAULT_SERVER_BIND_ADDRESS) or DEFAULT_SERVER_BIND_ADDRESS

    def _port_in_use(self, port: int, host: str) -> bool:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            return sock.connect_ex((host, port)) == 0

    def _port_probe_host(self) -> str:
        # A wildcard bind listens on every interface; probe loopback, which
        # is how the busy-port check has always behaved.
        bind = self.bind_address
        if bind == IPV4_WILDCARD:
            return LOCALHOST
        if bind == IPV6_WILDCARD:
            return IPV6_LOOPBACK
        return bind

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running:
            return

        port = self.port
        bind = self.bind_address
        if self._port_in_use(port, self._port_probe_host()):
            # Take the whole process down, tray icon included: with no HTTP
            # server there is nothing for the tray to do.
            logger.error(f"Port {port} is already in use; exiting")
            sys.exit(1)

        handler = partial(
            RecipeRequestHandler,
            directory=str(self.cfg.site_directory),
            source_directory=self.cfg.source_directory,
            on_markdown_saved=self.on_markdown_saved,
            on_config_saved=self.on_config_saved,
            on_recipes_deleted=self.on_recipes_deleted,
            config=self.cfg,
            auth=self.auth,
        )

        try:
            if ":" in bind:
                http_server = _ThreadingHTTPServerIPv6((bind, self.port), handler)
            else:
                http_server = _RecipeThreadingHTTPServer((bind, self.port), handler)
        except OSError:
            logger.exception(f"Failed to start server on {bind}:{self.port}")
            raise

        self._http_server = http_server
        self._thread = Thread(
            target=http_server.serve_forever,
            name="RecipeServer",
            daemon=True,
        )
        self._thread.start()

        logger.info(f"Server started on {bind}:{self.port}")
        address = f"[{bind}]" if ":" in bind else bind
        logger.info(f"Address: http://{address}:{self.port}")
        if bind not in {LOCALHOST, IPV6_LOOPBACK}:
            logger.warning(
                f"The site is bound to {bind} and has no authentication; anyone who can reach this machine can load and edit recipes over plain HTTP. Set server_bind_address to 127.0.0.1 to restrict access to this machine."
            )
        logger.info("Serve the site over HTTPS through a local reverse proxy to enable the dictation button.")

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
