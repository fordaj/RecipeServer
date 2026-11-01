from collections.abc import Mapping
from typing import TypedDict


class MetadataWarning(TypedDict):
    field: str
    label: str
    severity: str
    message: str


_REQUIRED_FIELDS = (
    ("ratings", "Ratings"),
    ("contributor", "Contributor"),
    ("createdOn", "CreatedOn"),
    ("meals", "Meals"),
    ("categories", "Category"),
    ("makes", "Makes"),
    ("difficulty", "Difficulty"),
)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value or all(_is_missing(item) for item in value)
    return False


def lint_recipe_metadata(metadata: Mapping[str, object]) -> list[MetadataWarning]:
    """Return structured warnings for missing recipe metadata."""
    warnings: list[MetadataWarning] = []
    for field, label in _REQUIRED_FIELDS:
        if _is_missing(metadata.get(field)):
            warnings.append(
                {
                    "field": field,
                    "label": label,
                    "severity": "warning",
                    "message": f"Missing {label.lower()}",
                }
            )
    return warnings
