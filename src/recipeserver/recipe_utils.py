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
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timezone

# Front matter uses the plural ``categories``; ``category`` is the legacy
# singular spelling, accepted on read and dropped on save.
CATEGORIES_FIELD = "categories"
LEGACY_CATEGORY_FIELD = "category"

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


def display_date(value: datetime) -> str:
    """Format a UTC datetime for server-rendered fallback text."""
    text = f"{value:%b} {value.day}"
    if datetime.now(timezone.utc).year != value.year:
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
