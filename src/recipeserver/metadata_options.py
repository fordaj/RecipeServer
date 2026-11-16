"""Collect the dropdown values that are already used in the recipe library.

The recipe editor and the comment/rating forms offer the values that are
already in use as dropdown options. They are read from the recipe Markdown
files when they are asked for, so they are never hard-coded into generated
pages or recipe front matter. The Markdown files stay the source of truth:
adding a value to a recipe makes it available to every other recipe right
away.

Besides the editor's metadata fields, the collector also reports the names
of everyone who has commented or rated a recipe, so the feedback forms can
offer them as options.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter

from ._logger import logger
from .recipe_utils import normalize_reviewer_name, read_categories

# Fields the editor fills from a dropdown. Multi-value fields hold a list of
# values; single-value fields hold exactly one.
MULTI_VALUE_FIELDS = ("meals", "categories", "cuisine", "tags")
SINGLE_VALUE_FIELDS = ("status", "contributor")
OPTION_FIELDS = (*MULTI_VALUE_FIELDS, *SINGLE_VALUE_FIELDS)

# The feedback forms fill their name dropdowns from these. Each maps to the
# front matter list it reads and the key inside each entry that holds the name.
FEEDBACK_OPTION_FIELDS = {
    "commenters": ("comments", "author"),
    "raters": ("ratings", "name"),
}


def _field_values(metadata: dict, field: str) -> list[str]:
    """Return the non-empty values one recipe stores for a single field."""
    value = metadata.get(field)
    if field == "categories":
        # Older recipes may use the singular field name.
        value = read_categories(metadata)

    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []

    values = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            values.append(text)
    return values


def _feedback_names(metadata: dict, field: str) -> list[str]:
    """Return the non-empty names one recipe stores in a feedback list."""
    list_field, name_key = FEEDBACK_OPTION_FIELDS[field]
    entries = metadata.get(list_field)
    if not isinstance(entries, list):
        return []

    names = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get(name_key)
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _recipe_files(root: Path) -> list[Path]:
    """Return the recipe Markdown files in the source tree."""
    if not root.is_dir():
        return []

    return [recipe_file for recipe_file in sorted(root.rglob("recipe.md")) if not recipe_file.is_symlink() and recipe_file.is_file()]


def collect_metadata_options(source_directory: Path) -> dict[str, list[dict[str, object]]]:
    """Return the values used by each dropdown field and how many recipes use them.

    Every value is reported with the number of recipes that use it, so the
    dropdowns can show how popular a value is next to the value itself. The
    ``commenters`` and ``raters`` lists report the names attached to the
    ``comments`` and ``ratings`` front matter entries the same way.
    """
    counts: dict[str, dict[str, int]] = {field: {} for field in (*OPTION_FIELDS, *FEEDBACK_OPTION_FIELDS)}
    root = Path(source_directory)

    for recipe_file in _recipe_files(root):
        try:
            metadata = frontmatter.loads(recipe_file.read_text(encoding="utf-8")).metadata
        except Exception:
            logger.warning(f"Skipping unreadable recipe while collecting metadata options: {recipe_file}")
            continue

        if not isinstance(metadata, dict):
            continue

        for field in OPTION_FIELDS:
            # A recipe counts once for every value it uses.
            for value in dict.fromkeys(_field_values(metadata, field)):
                counts[field][value] = counts[field].get(value, 0) + 1

        for field in FEEDBACK_OPTION_FIELDS:
            # A recipe counts once for every distinct name it carries,
            # comparing them the same way ratings are compared.
            seen = {}
            for value in _feedback_names(metadata, field):
                seen.setdefault(normalize_reviewer_name(value), value)
            for value in seen.values():
                counts[field][value] = counts[field].get(value, 0) + 1

    return {
        field: [{"value": value, "count": count} for value, count in sorted(values.items(), key=lambda item: (item[0].casefold(), item[0]))]
        for field, values in counts.items()
    }
