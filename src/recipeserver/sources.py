"""Shared source-list helpers for recipe pages and the index.

Both the recipe page (``markdown_to_html.extras``) and the index card
generator render the recipe's ``source`` front matter. They share the
normalization, title, and icon-selection rules so the two never drift.
"""

from __future__ import annotations

# Source formats that show an explicit "Source" detail on the index card.
TITLED_SOURCE_FORMATS = {"website", "book"}


def normalize_sources(metadata: dict) -> list[dict]:
    """Return the ``source`` metadata as a list of dicts."""
    sources = metadata.get("source")
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict)]


def source_format(source: dict) -> str:
    return str(source.get("format") or "").lower()


def source_title(source: dict) -> str:
    """Best-effort display title: ``title``, falling back to ``company`` for websites."""
    title = str(source.get("title") or "").strip()
    if not title and source_format(source) == "website":
        title = str(source.get("company") or "").strip()
    return title


def source_icon_key(fmt: str) -> str:
    """Map a source format to its icon key (``website``/``book``/``ai``/``user``)."""
    return fmt if fmt in {"website", "book", "ai"} else "user"
