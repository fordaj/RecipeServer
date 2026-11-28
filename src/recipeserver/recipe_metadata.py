"""The recipe front-matter schema shared by the editor, bulk edit, and assistant.

One field registry drives what the editor sends, what the per-field and bulk
endpoints accept, and what a model is allowed to change. Validation lives here
rather than in the HTTP handler so every caller enforces the same rules.
"""

from __future__ import annotations

from datetime import datetime

from .recipe_utils import (
    CATEGORIES_FIELD,
    LEGACY_CATEGORY_FIELD,
    clean_source_fields,
    collapse_status,
    is_finite_rating_score,
    new_recipe_id,
    normalize_legacy_category,
    normalize_reviewer_name,
    normalize_source_dict,
    utc_now_iso,
)

MAX_RATING_NAME_LENGTH = 100

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


# ----- Ratings (front-matter list) ----- #


def validate_rating_name(name: object, label: str) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_RATING_NAME_LENGTH:
        raise ValueError(f"{label} must be 1 to {MAX_RATING_NAME_LENGTH} characters")
    return name.strip()


def validate_rating_score(score: object, label: str) -> int | float:
    if not is_finite_rating_score(score):
        raise ValueError(f"{label} must be a number between 0 and 10")
    if score < 0 or score > 10:
        raise ValueError(f"{label} must be between 0 and 10")
    return score


def validate_bulk_rating(value: object) -> tuple[str, int | float] | None:
    """Validate a bulk rating override: add a named rating, overriding ties."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("'rating' must be an object with 'name' and 'rating'")

    name = validate_rating_name(value.get("name"), "'rating.name'")
    score = validate_rating_score(value.get("rating", value.get("score")), "'rating.rating'")
    return name, score


def apply_rating_override(ratings: object, name: str, score: int | float) -> list[dict]:
    """Return ratings with the named rating added or overridden in place."""
    current = ratings if isinstance(ratings, list) else []
    updated: list[dict] = []
    replaced = False
    normalized = normalize_reviewer_name(name)
    now = utc_now_iso()

    for item in current:
        if not isinstance(item, dict):
            continue

        existing = item.get("name")
        if isinstance(existing, str) and normalize_reviewer_name(existing) == normalized:
            updated.append({**item, "name": existing.strip(), "rating": score, "updated": now})
            replaced = True
        else:
            updated.append(item)

    if not replaced:
        updated.append({"name": name, "created": now, "updated": now, "id": new_recipe_id(), "rating": score})

    return updated


def _validate_rating_entry(index: int, rating: object) -> tuple[str, str, dict]:
    if not isinstance(rating, dict):
        raise ValueError(f"Rating {index + 1} must be an object")

    label = f"Rating {index + 1}"
    name = validate_rating_name(rating.get("name"), label)
    rating_id = rating.get("id")
    score = validate_rating_score(rating.get("rating"), label)

    if not isinstance(rating_id, str) or not rating_id.strip() or rating_id != rating_id.strip():
        raise ValueError(f"{label} must have an ID")

    for field in ("created", "updated"):
        timestamp = rating.get(field)
        if not isinstance(timestamp, str):
            raise ValueError(f"Rating {index + 1} must have a {field} timestamp")
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Rating {index + 1} has an invalid {field} timestamp") from exc

    normalized_rating = rating.copy()
    normalized_rating["name"] = name
    return normalize_reviewer_name(name), rating_id, normalized_rating


def validate_ratings(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("'ratings' must be a list")

    validated = []
    names = set()
    ids = set()

    for index, rating in enumerate(value):
        normalized_name, rating_id, normalized_rating = _validate_rating_entry(index, rating)

        if normalized_name in names:
            raise ValueError("There can only be one rating per name")
        names.add(normalized_name)

        if rating_id in ids:
            raise ValueError("Rating IDs must be unique")
        ids.add(rating_id)

        validated.append(normalized_rating)

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
