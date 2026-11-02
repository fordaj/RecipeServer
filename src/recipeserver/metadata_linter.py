from collections.abc import Mapping
from typing import TypedDict

from .metadata import RecipeMetadata


class MetadataWarning(TypedDict):
    field: str
    label: str
    severity: str
    message: str


def lint_recipe_metadata(metadata: RecipeMetadata | Mapping[str, object]) -> list[MetadataWarning]:
    """Return structured warnings for missing recipe metadata."""
    recipe_metadata = metadata if isinstance(metadata, RecipeMetadata) else RecipeMetadata.from_dict(dict(metadata))

    warnings: list[MetadataWarning] = []

    for field_name, label in RecipeMetadata.REQUIRED_FIELDS.items():
        if recipe_metadata.is_missing(field_name):
            warnings.append(
                {
                    "field": field_name,
                    "label": label,
                    "severity": "warning",
                    "message": f"Missing {label.lower()}",
                }
            )

    return warnings
