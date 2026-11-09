"""Shared helpers for recipe metadata and JSON serialization.

These functions centralize small pieces of logic that are used in more than
one module. They are intentionally narrow: keep behavior stable and avoid
adding abstraction that hides meaning.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime, time, timezone


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


def slug_to_title(slug: str) -> str:
    """Fallback title from a recipe directory slug."""
    return slug.replace("-", " ").replace("_", " ").title()
