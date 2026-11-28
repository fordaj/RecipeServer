"""The recipe front-matter schema shared by the editor, bulk edit, and assistant.

One field registry drives what the editor sends, what the per-field and bulk
endpoints accept, and what a model is allowed to change. Validation lives here
rather than in the HTTP handler so every caller enforces the same rules.
"""

from __future__ import annotations

from .recipe_utils import (
    CATEGORIES_FIELD,
    LEGACY_CATEGORY_FIELD,
    clean_source_fields,
    collapse_status,
    normalize_legacy_category,
    normalize_source_dict,
)

# Field name → value kind. The metadata API and the JS editor derive their
# accepted fields from this registry.
EDITOR_METADATA_FIELDS = {
    "tags": "string_list",
    "cuisine": "string_list",
    "categories": "string_list",
    "meals": "string_list",
    "makes": "non_negative_integer",
    "difficulty": "number",
    "contributor": "string",
    "status": "string",
    "createdOn": "string",
    "updatedOn": "string",
    "archived": "boolean",
    "source": "object",
}

# Fields a bulk edit may overwrite. ``updatedOn`` is always refreshed by the
# server, so it is never accepted as a bulk-editable field.
BULK_EDITABLE_FIELDS = tuple(field for field in EDITOR_METADATA_FIELDS if field != "updatedOn")

# The multi-value fields, derived from the registry rather than restated in
# the AI drafting and dropdown code.
STRING_LIST_FIELDS = tuple(field for field, kind in EDITOR_METADATA_FIELDS.items() if kind == "string_list")


def canonical_category_field(field_name: str) -> str:
    """Map the legacy singular ``category`` field name onto ``categories``."""
    return CATEGORIES_FIELD if field_name == LEGACY_CATEGORY_FIELD else field_name


def metadata_field_name(path: str) -> str | None:
    """Extract the metadata field name from an API path, if present."""
    field_name = path.rsplit("/", 1)[-1]
    return canonical_category_field(field_name) if field_name else None


def drop_legacy_category(metadata: dict) -> None:
    """Remove the legacy singular field once the plural one has been written."""
    metadata.pop(LEGACY_CATEGORY_FIELD, None)


def editor_metadata(metadata: dict) -> dict:
    """Return editable metadata, mapping the legacy singular category field."""
    merged = dict(metadata)
    normalize_legacy_category(merged)
    values = {field: merged.get(field) for field in EDITOR_METADATA_FIELDS}

    # Status is a single string; older recipes may store a list.
    values["status"] = collapse_status(values.get("status"))

    # The editor edits one source at a time; older recipes may store a list.
    values["source"] = normalize_source_dict(values["source"])

    # ``archived`` defaults to False when absent (or not a boolean).
    values["archived"] = metadata.get("archived") is True

    return values


def source_is_empty(source: dict | None) -> bool:
    return not source or not any(value is not None for value in source.values())


def apply_source_metadata(existing: dict, value: dict | None) -> None:
    new_source = None if source_is_empty(value) else value
    current = existing.get("source")

    if isinstance(current, list):
        sources = [source for source in current if isinstance(source, dict)]
        if new_source is None:
            sources = sources[1:]
        elif sources:
            sources[0] = new_source
        else:
            sources = [new_source]

        if sources:
            existing["source"] = sources
        else:
            existing.pop("source", None)
        return

    if new_source is None:
        existing.pop("source", None)
    else:
        existing["source"] = new_source


def apply_editor_metadata(existing: dict, values: dict) -> None:
    """Apply validated editor fields while preserving extra sources."""
    for field, value in values.items():
        if field == "source":
            apply_source_metadata(existing, value)
        else:
            existing[field] = value


def validate_string_list_field(field: str, value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"'{field}' must be a list of strings or null")
    return value


def validate_string_field(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{field}' must be a string or null")
    return value


def validate_number_field(field: str, value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{field}' must be a number or null")
    return value


def validate_boolean_field(field: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"'{field}' must be a boolean or null")
    return value


def validate_source_field(field: str, value: object) -> dict | None:
    if isinstance(value, list):
        source = normalize_source_dict(value)
        if source is None:
            return None
    elif not isinstance(value, dict):
        raise ValueError(f"'{field}' must be an object or null")
    else:
        source = value
    return clean_source_fields(source)


def validate_makes(value: object) -> int | None:
    """Validate a ``makes`` counter value for the per-field metadata endpoint."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("'makes' must be a non-negative integer or null")
    return value


def validate_editor_field(field: str, expected_type: str, value: object) -> object:
    validators = {
        "string_list": validate_string_list_field,
        "string": validate_string_field,
        "non_negative_integer": lambda field, value: validate_makes(value),
        "number": validate_number_field,
        "boolean": validate_boolean_field,
    }
    if expected_type in validators:
        return validators[expected_type](field, value)
    if expected_type == "object" and field == "source":
        return validate_source_field(field, value)
    return value


def validate_editor_metadata(metadata: object) -> dict:
    if not isinstance(metadata, dict):
        raise ValueError("Expected a metadata object")

    validated = {}
    for field, expected_type in EDITOR_METADATA_FIELDS.items():
        value = metadata.get(field)
        if value is None:
            validated[field] = None
        else:
            validated[field] = validate_editor_field(field, expected_type, value)

    return validated


def validate_assistant_metadata(metadata: object) -> dict:
    """Validate a partial editor-metadata object for the AI assistant.

    Only the keys present are validated and returned; ``updatedOn`` (which the
    server always manages) and unknown fields are rejected, so a misbehaving
    model cannot sneak in an arbitrary front-matter key. A value of null clears
    the field, matching the editor's semantics.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Expected a metadata object")

    validated = {}
    for key, value in metadata.items():
        if key == "updatedOn":
            raise ValueError("'updatedOn' is managed by the server")
        expected_type = EDITOR_METADATA_FIELDS.get(key)
        if expected_type is None:
            raise ValueError(f"Unknown metadata field: {key}")
        if value is None:
            validated[key] = None
        else:
            validated[key] = validate_editor_field(key, expected_type, value)

    return validated
