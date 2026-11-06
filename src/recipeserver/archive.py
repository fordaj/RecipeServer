"""On-demand 7z archives of the recipe source and the generated site.

The sandwich menu (see ``menu.py``) links to these endpoints. Building the
archive on request (rather than pre-generating it during ``regen()``) keeps
downloads current without storing another copy of every recipe, and lets the
server stream the result with a browser-timezone-aware filename.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import py7zr

ARCHIVE_KINDS = ("source", "site")

_KIND_LABELS = {"source": "Source", "site": "Site"}

_ARCHIVE_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def archive_filename(kind: str, archive_date: date) -> str:
    """Return the download filename for an archive kind and date."""
    if kind not in _KIND_LABELS:
        raise ValueError(f"Unknown archive kind: {kind!r}")
    return f"{archive_date.isoformat()}_RecipeServer_{_KIND_LABELS[kind]}.7z"


def utc_today(fallback: date | None = None) -> date:
    """Today in UTC (used when the browser does not supply a date)."""
    if fallback is not None:
        return fallback
    return datetime.now(timezone.utc).date()


def resolve_archive_date(raw: str | None, fallback: date | None = None) -> date:
    """Parse the browser-supplied ``YYYY-MM-DD`` date.

    The browser computes this from local components (see ``menu.js``) so the
    filename reflects the browser's timezone rather than UTC. When no date is
    supplied the server falls back to the UTC date. Anything else is rejected
    so a malformed value can never leak into the filename.
    """
    if raw is None or raw == "":
        return utc_today(fallback)

    value = raw.strip()
    if _ARCHIVE_DATE_RE.fullmatch(value) is None:
        raise ValueError("Expected a date in YYYY-MM-DD format")

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Expected a valid date in YYYY-MM-DD format") from exc


def create_archive(source_directory: Path, archive_path: Path) -> None:
    """Write a 7z archive of ``source_directory`` to ``archive_path``."""
    source_directory = Path(source_directory)
    if not source_directory.is_dir():
        raise FileNotFoundError(f"Archive directory not found: {source_directory}")

    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with py7zr.SevenZipFile(archive_path, mode="w") as archive:
        # Archive relative to a top-level folder named after the directory
        # (e.g. ``site/...`` or the source folder) instead of an absolute path.
        archive.writeall(source_directory, arcname=source_directory.name)
