"""Domain operations behind the history endpoints."""

from __future__ import annotations

import pytest

from recipeserver import history
from recipeserver.recipe_history_api import (
    InvalidSnapshotRequest,
    SnapshotNotFound,
    compare_snapshot,
    parse_history_query,
    read_snapshot,
    sanitize_preview_html,
    snapshot_payload,
)

RECIPE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_parse_history_query_returns_only_single_nonempty_values():
    assert parse_history_query("path=a%2Frecipe.md&snapshot=s1&recipeId=r") == ("a/recipe.md", "s1", "r")
    assert parse_history_query("path=&snapshot=s1&snapshot=s2") == (None, None, None)


def test_snapshot_payload_and_read_snapshot_use_the_store():
    assert snapshot_payload(RECIPE_ID) == []
    path = history.create_snapshot(RECIPE_ID, "# Old\n")
    assert path is not None

    payload = snapshot_payload(RECIPE_ID)
    assert len(payload) == 1
    assert set(payload[0]) == {"id", "created", "size"}
    assert read_snapshot(RECIPE_ID, payload[0]["id"]) == "# Old\n"


def test_read_snapshot_reports_missing_and_malformed_ids():
    with pytest.raises(InvalidSnapshotRequest, match="Expected a snapshot parameter"):
        read_snapshot(RECIPE_ID, None)
    with pytest.raises(InvalidSnapshotRequest, match="valid snapshot"):
        read_snapshot(RECIPE_ID, "not-an-id")
    with pytest.raises(SnapshotNotFound):
        read_snapshot(RECIPE_ID, history.make_snapshot_id())


def test_compare_snapshot_builds_a_unified_diff():
    payload = compare_snapshot("# Old\n", "# New\n", path="a/recipe.md", recipe_id=RECIPE_ID, snapshot_id="s1")
    assert "-# Old" in payload["diff"]
    assert "+# New" in payload["diff"]
    assert payload["snapshot"]["id"] == "s1"
    assert payload["path"] == "a/recipe.md"


def test_sanitize_preview_html_removes_scripts_and_page_chrome():
    rendered = '<html><header class="recipe-header">Menu</header><script>alert(1)</script><main>Body</main></html>'
    result = sanitize_preview_html(rendered)
    assert "<script" not in result
    assert "Menu" not in result
    assert "<main>Body</main>" in result
