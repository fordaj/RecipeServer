"""Collect the metadata values that are already used in the recipe library.

The recipe editor offers the values that are already in use as dropdown
options. They are read from the recipe Markdown files when they are asked
for, so they are never hard-coded into generated pages or recipe front
matter. The Markdown files stay the source of truth: adding a value to a
recipe makes it available to every other recipe right away.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter

from ._logger import logger

# Fields the editor fills from a dropdown. Multi-value fields hold a list of
# values; single-value fields hold exactly one.
MULTI_VALUE_FIELDS = ("meals", "categories", "cuisine", "tags")
SINGLE_VALUE_FIELDS = ("status", "contributor")
OPTION_FIELDS = (*MULTI_VALUE_FIELDS, *SINGLE_VALUE_FIELDS)


def _field_values(metadata: dict, field: str) -> list[str]:
    """Return the non-empty values one recipe stores for a single field."""
    value = metadata.get(field)
    if field == "categories" and not value:
        # Older recipes may use the singular field name.
        value = metadata.get("category")

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


def _recipe_files(root: Path) -> list[Path]:
    """Return the recipe Markdown files in the source tree."""
    if not root.is_dir():
        return []

    return [recipe_file for recipe_file in sorted(root.rglob("recipe.md")) if not recipe_file.is_symlink() and recipe_file.is_file()]


def collect_metadata_options(source_directory: Path) -> dict[str, list[str]]:
    """Return the distinct values used by each dropdown-backed metadata field."""
    options: dict[str, set[str]] = {field: set() for field in OPTION_FIELDS}
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
            options[field].update(_field_values(metadata, field))

    return {field: sorted(values, key=lambda value: (value.casefold(), value)) for field, values in options.items()}
