from collections.abc import Mapping
from typing import TypedDict

from .recipe_utils import is_missing_metadata_value, read_categories


class MetadataWarning(TypedDict):
    field: str
    label: str
    severity: str
    message: str


_REQUIRED_FIELDS = (
    ("ratings", "Ratings"),
    ("contributor", "Contributor"),
    ("createdOn", "Contribution date"),
    ("meals", "Meals"),
    ("categories", "Categories"),
    ("makes", "Makes"),
    ("difficulty", "Difficulty"),
)


def lint_recipe_metadata(metadata: Mapping[str, object]) -> list[MetadataWarning]:
    """Return structured warnings for missing recipe metadata."""
    warnings: list[MetadataWarning] = []
    for field, label in _REQUIRED_FIELDS:
        value = metadata.get(field)
        if field == "categories" and is_missing_metadata_value(value) and not is_missing_metadata_value(read_categories(metadata)):
            continue
        if is_missing_metadata_value(value):
            warnings.append(
                {
                    "field": field,
                    "label": label,
                    "severity": "warning",
                    "message": f"Missing {label.lower()}",
                }
            )
    return warnings
