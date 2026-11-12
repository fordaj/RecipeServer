"""Recipe scheduling for the calendar view.

A recipe is scheduled by listing calendar dates in its YAML front matter::

    scheduledOn:
      - '2026-11-15'
      - '2026-11-22'

The field is optional and holds plain ``YYYY-MM-DD`` strings, so a recipe can
be planned for several days. The calendar reads every recipe in the source
tree and groups them by date; writes go back into the same front matter, so
the Markdown files stay the single source of truth.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

import frontmatter

from ._logger import logger
from .image_handler import get_first_image_in_dir
from .recipe_utils import slug_to_title

# The front matter field that holds the scheduled dates.
SCHEDULED_FIELD = "scheduledOn"

# A calendar date, written as YYYY-MM-DD.
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The first level-one heading of a recipe, used as its title.
_HEADING_PATTERN = re.compile(r"^ {0,3}#\s+(.*?)\s*#*\s*$", re.MULTILINE)


def _date_text(value: object) -> str:
    """Return the text of a date value.

    YAML turns an unquoted date into a ``date`` object, so those are turned
    back into their ISO text.
    """
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _is_date(text: str) -> bool:
    """Return True when the text is a real calendar date."""
    if not DATE_PATTERN.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def normalize_dates(value: object) -> list[str]:
    """Return the valid dates in *value*, oldest first.

    Accepts a single date or a list of dates. Unreadable entries are dropped
    rather than raising, so one bad value cannot hide a whole recipe.
    """
    if isinstance(value, (str, date)):
        value = [value]
    if not isinstance(value, list):
        return []

    dates: list[str] = []
    for item in value:
        text = _date_text(item)
        if _is_date(text) and text not in dates:
            dates.append(text)

    return sorted(dates)


def parse_dates(value: object) -> list[str]:
    """Return the dates in *value*, raising ``ValueError`` on a bad one."""
    if not isinstance(value, list):
        raise ValueError("Expected a list of dates")

    dates: list[str] = []
    for item in value:
        text = _date_text(item)
        if not _is_date(text):
            raise ValueError(f"Invalid scheduled date: {text}")
        if text not in dates:
            dates.append(text)

    return sorted(dates)


def recipe_title(content: str, metadata: Mapping, folder_name: str) -> str:
    """Return the title of a recipe: its heading, front matter, or folder.

    The first level-one heading wins, unless it sits inside a fenced code
    block.
    """
    in_fence = False

    for line in content.splitlines():
        stripped = line.lstrip()

        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue

        if in_fence:
            continue

        match = _HEADING_PATTERN.match(line)
        if match and match.group(1).strip():
            return match.group(1).strip()

    return str(metadata.get("title") or "").strip() or slug_to_title(folder_name)


def read_schedules(source_directory: Path) -> list[dict]:
    """Return the schedule of every recipe in the source tree."""
    entries: list[dict] = []

    for markdown in sorted(source_directory.rglob("recipe.md")):
        if not markdown.is_file():
            continue

        try:
            post = frontmatter.loads(markdown.read_text(encoding="utf-8"))
        except Exception:
            logger.exception(f'Failed to read the schedule of "{markdown}", skipping it')
            continue

        relative_path = markdown.relative_to(source_directory).as_posix()
        image = get_first_image_in_dir(markdown.parent)

        entries.append(
            {
                "path": relative_path,
                "title": recipe_title(post.content, post.metadata, markdown.parent.name),
                "image": f"/{image.relative_to(source_directory).as_posix()}" if image else "",
                "url": "/" + Path(relative_path).with_suffix(".html").as_posix(),
                "dates": normalize_dates(post.metadata.get(SCHEDULED_FIELD)),
            }
        )

    return entries


def write_dates(markdown_path: Path, dates: list[str]) -> list[str]:
    """Write the scheduled dates into a recipe's YAML front matter."""
    post = frontmatter.loads(markdown_path.read_text(encoding="utf-8"))
    cleaned = parse_dates(dates)

    if cleaned:
        post.metadata[SCHEDULED_FIELD] = cleaned
    else:
        post.metadata.pop(SCHEDULED_FIELD, None)

    markdown_path.write_text(frontmatter.dumps(post), encoding="utf-8", newline="")
    return cleaned
