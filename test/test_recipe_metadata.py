"""The canonical front-matter schema and validators."""

from __future__ import annotations

import pytest

from recipeserver.recipe_metadata import (
    BULK_EDITABLE_FIELDS,
    EDITOR_METADATA_FIELDS,
    apply_editor_metadata,
    editor_metadata,
    metadata_field_name,
    source_is_empty,
    validate_assistant_metadata,
    validate_editor_metadata,
)


def test_editor_metadata_maps_legacy_category_and_normalizes_values():
    values = editor_metadata({"category": "Dinner", "status": ["planned"], "archived": "yes", "source": [{"author": " A "}]})

    assert values["categories"] == ["Dinner"]
    assert values["status"] == "planned"
    assert values["archived"] is False
    assert values["source"] == {"author": " A "}


def test_editor_metadata_defaults_archived_and_missing_fields():
    values = editor_metadata({})
    assert values["archived"] is False
    assert set(values) == set(EDITOR_METADATA_FIELDS)


def test_metadata_field_name_canonicalizes_the_legacy_spelling():
    assert metadata_field_name("/api/metadata/category") == "categories"
    assert metadata_field_name("/api/metadata/tags") == "tags"
    assert metadata_field_name("") is None


def test_validate_editor_metadata_accepts_null_and_checks_types():
    validated = validate_editor_metadata({"tags": None, "makes": 2})
    assert validated["tags"] is None
    assert validated["makes"] == 2

    for bad in ({"tags": "Dinner"}, {"makes": -1}, {"archived": "true"}, {"difficulty": "hard"}):
        with pytest.raises(ValueError):
            validate_editor_metadata(bad)


def test_validate_assistant_metadata_only_accepts_editor_fields():
    assert validate_assistant_metadata({"tags": ["x"]}) == {"tags": ["x"]}

    with pytest.raises(ValueError, match="updatedOn"):
        validate_assistant_metadata({"updatedOn": "now"})
    with pytest.raises(ValueError, match="Unknown metadata field"):
        validate_assistant_metadata({"recipe_id": "abc"})


def test_apply_editor_metadata_preserves_extra_sources():
    existing = {"source": [{"author": "first"}, {"author": "second"}], "kept": 1}
    apply_editor_metadata(existing, {"source": {"author": "new"}, "tags": ["x"]})

    assert existing["source"][0] == {"author": "new"}
    assert existing["source"][1] == {"author": "second"}
    assert existing["tags"] == ["x"]
    assert existing["kept"] == 1


def test_source_is_empty():
    assert source_is_empty(None)
    assert source_is_empty({})
    assert not source_is_empty({"author": "a"})


def test_bulk_editable_fields_exclude_the_server_managed_timestamp():
    assert "updatedOn" not in BULK_EDITABLE_FIELDS
    assert set(BULK_EDITABLE_FIELDS) == set(EDITOR_METADATA_FIELDS) - {"updatedOn"}
