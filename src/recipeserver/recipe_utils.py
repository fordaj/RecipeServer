"""Shared helpers for recipe metadata and JSON serialization.

These functions centralize small pieces of logic that are used in more than
one module. They are intentionally narrow: keep behavior stable and avoid
adding abstraction that hides meaning.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime


def json_default(value: object) -> str:
    """Serialize YAML/date values that the JSON encoder does not understand."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def is_finite_rating_score(score: object) -> bool:
    """Return True when *score* is a usable numeric rating value."""
    return (
        isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(score)
    )


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
