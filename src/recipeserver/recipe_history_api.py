"""History API domain operations: querying, shaping, diffing and previewing.

The HTTP handler owns routing and status codes; this module owns the work
behind the history endpoints. It reads the snapshot store, shapes the payloads
the dialog consumes, renders a snapshot in a scratch directory, and builds a
unified diff — none of which needs a request or a response object.
"""

from __future__ import annotations

import base64
import re
import shutil
import tempfile
from mimetypes import guess_type
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote

from bs4 import BeautifulSoup

from .image_handler import IMAGE_EXTENSIONS
from .recipe_paths import RECIPE_FILENAME
from . import history as recipe_history

_PREVIEW_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_PREVIEW_HEADER_RE = re.compile(r"<header class=\"recipe-header\">.*?</header>", re.DOTALL | re.IGNORECASE)


class InvalidSnapshotRequest(ValueError):
    """The snapshot parameter is missing or malformed."""


class SnapshotNotFound(LookupError):
    """The snapshot does not exist in the store."""


def parse_history_query(query: str) -> tuple[str | None, str | None, str | None]:
    """Extract ``path``, ``snapshot``, and ``recipeId`` from a query string."""
    parsed = parse_qs(query)

    def one(key: str) -> str | None:
        values = parsed.get(key, [])
        return values[0] if len(values) == 1 and values[0] else None

    return one("path"), one("snapshot"), one("recipeId")


def snapshot_payload(recipe_id: str) -> list[dict]:
    return [
        {
            "id": snapshot.id,
            "created": snapshot.created.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "size": snapshot.size,
        }
        for snapshot in recipe_history.list_snapshots(recipe_id)
    ]


def read_snapshot(recipe_id: str, snapshot_id: str | None) -> str:
    if snapshot_id is None:
        raise InvalidSnapshotRequest("Expected a snapshot parameter")
    if not recipe_history.is_valid_snapshot_id(snapshot_id):
        raise InvalidSnapshotRequest("Expected a valid snapshot")
    try:
        return recipe_history.read_snapshot(recipe_id, snapshot_id)
    except FileNotFoundError as exc:
        raise SnapshotNotFound("Snapshot not found") from exc
    except recipe_history.HistoryError as exc:
        raise InvalidSnapshotRequest("Expected a valid snapshot") from exc


def compare_snapshot(content: str, current: str, *, path: str | None, recipe_id: str, snapshot_id: str) -> dict:
    """Build the compare payload for one snapshot against the current recipe."""
    import difflib

    diff = "\n".join(difflib.unified_diff(content.splitlines(), current.splitlines(), fromfile="snapshot", tofile="current", n=3, lineterm=""))
    snapshot_info = next((snapshot for snapshot in recipe_history.list_snapshots(recipe_id) if snapshot.id == snapshot_id), None)
    created = snapshot_info.created.isoformat(timespec="milliseconds").replace("+00:00", "Z") if snapshot_info else None
    return {
        "path": path,
        "recipeId": recipe_id,
        "snapshot": {"id": snapshot_id, "created": created},
        "diff": diff,
    }


def sanitize_preview_html(rendered: str) -> str:
    """Neutralize a rendered recipe page for use as a historical preview."""
    return _PREVIEW_HEADER_RE.sub("", _PREVIEW_SCRIPT_RE.sub("", rendered))


def render_preview(snapshot_content: str, current_recipe: Path | None) -> str:
    """Render a snapshot through the recipe pipeline with scripts stripped.

    The snapshot is converted in a scratch directory, so the current recipe is
    never touched. Its images are copied in so the hero accent resolves, then
    inlined as data URIs so the preview frame is self-contained.
    """
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

    sanitized = sanitize_preview_html(rendered)
    if recipe_directory is None:
        return sanitized

    soup = BeautifulSoup(sanitized, "html.parser")
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
