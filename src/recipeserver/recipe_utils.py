"""Shared helpers for recipe metadata and JSON serialization.

These functions centralize small pieces of logic that are used in more than
one module. They are intentionally narrow: keep behavior stable and avoid
adding abstraction that hides meaning.
"""

from __future__ import annotations

import html
import math
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timezone

# Front matter uses the plural ``categories``; ``category`` is the legacy
# singular spelling, accepted on read and dropped on save.
CATEGORIES_FIELD = "categories"
LEGACY_CATEGORY_FIELD = "category"

# Every recipe carries a stable UUIDv4 in its front matter as ``recipe_id``.
# Identity never depends on the file path, so renames and moves keep history.
RECIPE_ID_FIELD = "recipe_id"

# Windows device names may not be used as a file or folder name, with or
# without an extension. Shared by recipe folder naming and image validation.
WINDOWS_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{number}" for number in range(1, 10)} | {f"LPT{number}" for number in range(1, 10)}
)


def is_windows_reserved_name(stem: str) -> bool:
    return stem.upper() in WINDOWS_RESERVED_FILENAMES


# Source fields the editor and the AI drafts know how to render and save.
SOURCE_FIELDS = ("author", "title", "format", "url")
# Canonical labels for the source format, keyed by its lower-cased spelling.
SOURCE_FORMAT_LABELS = {
    "website": "Website",
    "ai": "AI",
    "book": "Book",
    "other": "Other",
}


def as_list(value: object) -> list:
    """Return metadata values as a list, accepting scalar strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def json_default(value: object) -> str:
    """Serialize YAML/date values that the JSON encoder does not understand."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def parse_metadata_datetime(value: object) -> datetime | None:
    """Parse a metadata timestamp as a timezone-aware UTC datetime.

    Accepts ``datetime``, ``date``, and ISO 8601 strings (including ``Z``).
    Naive datetimes are interpreted as UTC. Returns ``None`` when the value
    cannot be parsed.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def utc_now_iso() -> str:
    """Current UTC time as a millisecond ISO string ending in ``Z``."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def is_finite_rating_score(score: object) -> bool:
    """Return True when *score* is a usable numeric rating value."""
    return isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score)


def iter_valid_rating_entries(ratings: object) -> Iterable[tuple[str, int | float]]:
    """Yield ``(reviewer_name, score)`` for each valid rating entry.

    Invalid entries are skipped rather than raising, matching the read paths
    used by index and recipe rendering.
    """
    if not isinstance(ratings, list):
        return

    for rating in ratings:
        if not isinstance(rating, dict):
            continue

        score = rating.get("rating")
        if not is_finite_rating_score(score):
            continue

        name = rating.get("name")
        yield (name.strip() if isinstance(name, str) else ""), score


def normalize_reviewer_name(name: str) -> str:
    """Normalize a reviewer name for case-insensitive comparison."""
    return unicodedata.normalize("NFKC", name.strip()).casefold()


def is_date_only(value: object) -> bool:
    """Return True when a metadata value represents a calendar date only."""
    if isinstance(value, datetime):
        return False
    if isinstance(value, date):
        return True
    if isinstance(value, str):
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()) is not None
    return False


def display_date(value: datetime, now: datetime | None = None) -> str:
    """Format a UTC datetime for server-rendered fallback text.

    The browser's `assets/date-labels.js` applies the same month/day rule, with
    an injectable ``now`` so the shared contract can be tested on both sides.
    """
    text = f"{value:%b} {value.day}"
    current = now or datetime.now(timezone.utc)
    if current.year != value.year:
        text += f", {value.year}"
    return text


def is_missing_metadata_value(value: object) -> bool:
    """Return True when *value* carries no metadata information."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value or all(is_missing_metadata_value(item) for item in value)
    return False


def read_categories(metadata: Mapping[str, object]) -> object:
    """Return ``categories``, falling back to the legacy singular ``category``."""
    value = metadata.get(CATEGORIES_FIELD)
    if is_missing_metadata_value(value):
        return metadata.get(LEGACY_CATEGORY_FIELD)
    return value


def normalize_legacy_category(metadata: dict) -> None:
    """Fold the legacy singular ``category`` into ``categories`` (in place)."""
    legacy = metadata.pop(LEGACY_CATEGORY_FIELD, None)
    if legacy is None or not is_missing_metadata_value(metadata.get(CATEGORIES_FIELD)):
        return
    if isinstance(legacy, str):
        legacy = [item.strip() for item in legacy.split(",") if item.strip()]
    metadata[CATEGORIES_FIELD] = legacy


def collapse_status(status: object) -> str | None:
    """Collapse a ``status`` value to a single trimmed string, or ``None``."""
    if isinstance(status, list):
        return next((item.strip() for item in status if isinstance(item, str) and item.strip()), None)
    if isinstance(status, str):
        return status.strip() or None
    return None


def normalize_source_dict(source: object) -> dict | None:
    """Coerce a ``source`` value (possibly a legacy list) to a single dict."""
    if isinstance(source, list):
        source = next((item for item in source if isinstance(item, dict)), None)
    return source if isinstance(source, dict) else None


def clean_source_fields(source: dict, *, format_labels: Mapping[str, str] | None = None) -> dict:
    """Rebuild *source* with the known fields, stripping string values."""
    cleaned = {}
    for field_name in SOURCE_FIELDS:
        value = source.get(field_name)
        cleaned[field_name] = (value.strip() or None) if isinstance(value, str) else None
    source_format = cleaned["format"]
    if format_labels is not None and isinstance(source_format, str):
        cleaned["format"] = format_labels.get(source_format.casefold(), source_format)
    return cleaned


def meta_time_html(raw_value: object, text_prefix: str = "") -> str | None:
    """Return the recipe-meta "· <time>" fragment, or ``None`` when unparseable.

    Shared by the soup-based recipe extras and the string-built index markup so
    both emit identical separator and ``<time>`` markup. Date-only values render
    as a bare calendar date; timestamps render in browser-local time via
    ``data-local-time``. *text_prefix* (for example ``"Edited "``) is prepended to
    the displayed text and emitted as ``data-time-prefix`` so the browser-side
    script can rebuild the label.
    """
    parsed = parse_metadata_datetime(raw_value)
    if parsed is None:
        return None

    separator = f'<span class="recipe-meta__separator" aria-hidden="true">·</span>'

    if is_date_only(raw_value):
        time_attrs = f'datetime="{parsed.date().isoformat()}"'
    else:
        time_attrs = f'datetime="{parsed.isoformat()}" data-local-time="true"'
        if text_prefix:
            time_attrs += f' data-time-prefix="{html.escape(text_prefix, quote=True)}"'

    text = f"{text_prefix}{display_date(parsed)}"
    return f"{separator}<time {time_attrs}>{html.escape(text)}</time>"


def slug_to_title(slug: str) -> str:
    """Fallback title from a recipe directory slug."""
    return slug.replace("-", " ").replace("_", " ").title()


_FIRST_HEADING_RE = re.compile(r"^ {0,3}#\s+(.*?)\s*#*\s*$")


def first_heading(text: str) -> str | None:
    """Return the first level-one Markdown heading, ignoring fenced code.

    The title of a recipe page, its index card, and the assistant's tool output
    all come from this one rule: first ``#`` heading outside a fence, otherwise
    the caller falls back to front matter or the directory slug.
    """
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _FIRST_HEADING_RE.match(line)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


# ----- Recipe identity (``recipe_id``) ----- #
#
# The helpers here work textually on the Markdown source instead of rounding
# through a YAML parser, so inserting or replacing the ``recipe_id`` line
# never reformats the author's front matter. Snapshots in the history store
# are preserved byte-for-byte, which is why these functions keep newline
# style and surrounding formatting intact.

_FRONTMATTER_RE = re.compile(
    r"\A(?P<open>---[ \t]*\r?\n)(?P<frontmatter>.*?)(?P<close>\r?\n---[ \t]*(?:\r?\n|\Z))",
    re.DOTALL,
)

_RECIPE_ID_LINE_RE = re.compile(r"(?m)^recipe_id:[ \t]*[\"']?(?P<value>[^\"'\r\n]+?)[\"']?[ \t]*$")


def new_recipe_id() -> str:
    """Return a fresh UUIDv4 recipe identifier."""
    return str(uuid.uuid4())


def is_valid_recipe_id(value: object) -> bool:
    """Return True when *value* is a parseable UUID."""
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value.strip())
    except ValueError, AttributeError, TypeError:
        return False
    return True


def canonical_recipe_id(value: str) -> str:
    """Return the canonical lower-case spelling of a valid UUID."""
    return str(uuid.UUID(value.strip()))


def _detect_newline(content: str) -> str:
    return "\r\n" if "\r\n" in content else "\n"


def extract_recipe_id(content: str) -> str | None:
    """Return the ``recipe_id`` from the front matter, or ``None``.

    A present but invalid value is treated as missing so callers assign a
    fresh identifier instead of trusting it.
    """
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        return None
    id_match = _RECIPE_ID_LINE_RE.search(match.group("frontmatter"))
    if id_match is None:
        return None
    value = id_match.group("value").strip()
    return canonical_recipe_id(value) if is_valid_recipe_id(value) else None


def set_recipe_id(content: str, recipe_id: str) -> str:
    """Return *content* with ``recipe_id`` set to *recipe_id*.

    The rest of the document is preserved byte-for-byte: the line is inserted
    right after the opening ``---`` of an existing front matter block, or a
    new block is prepended when the document has none. An existing
    ``recipe_id`` line (even an invalid one) is replaced.
    """
    recipe_id = canonical_recipe_id(recipe_id)
    newline = _detect_newline(content)
    id_line = f"recipe_id: {recipe_id}"

    match = _FRONTMATTER_RE.match(content)
    if match is None:
        return f"---{newline}{id_line}{newline}---{newline}" + content

    frontmatter_text = match.group("frontmatter")
    if _RECIPE_ID_LINE_RE.search(frontmatter_text):
        new_frontmatter = _RECIPE_ID_LINE_RE.sub(id_line, frontmatter_text, count=1)
    else:
        new_frontmatter = id_line + newline + frontmatter_text
    return content[: match.start("frontmatter")] + new_frontmatter + content[match.end("frontmatter") :]
