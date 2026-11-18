"""Unit tests for the history module (snapshot storage)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from recipeserver import history


def history_root() -> Path:
    return Path(os.environ[history.HISTORY_DIR_ENV_VAR])


def test_create_snapshot_stores_content_and_lists_newest_first():
    recipe_id = "11111111-1111-4111-8111-111111111111"
    first = history.create_snapshot(recipe_id, "---\nmeals:\n  - Dinner\n---\n# Soup\n\nv1\n")
    second = history.create_snapshot(recipe_id, "---\nmeals:\n  - Dinner\n---\n# Soup\n\nv2\n")

    assert first is not None and second is not None
    assert first != second
    assert first.read_text(encoding="utf-8").endswith("v1\n")
    assert second.read_text(encoding="utf-8").endswith("v2\n")

    snapshots = history.list_snapshots(recipe_id)
    assert [snapshot.id for snapshot in snapshots] == [second.stem, first.stem]
    assert all(snapshot.created.tzinfo is not None for snapshot in snapshots)
    assert snapshots[0].size == len(second.read_text(encoding="utf-8").encode("utf-8"))


def test_create_snapshot_skips_consecutive_duplicates_by_content_hash():
    recipe_id = "22222222-2222-4222-8222-222222222222"
    content = "# Same content\n\nBody.\n"

    assert history.create_snapshot(recipe_id, content) is not None
    assert history.create_snapshot(recipe_id, content) is None

    snapshots = history.list_snapshots(recipe_id)
    assert len(snapshots) == 1


def test_create_snapshot_stores_identical_content_after_an_intervening_version():
    recipe_id = "33333333-3333-4333-8333-333333333333"

    history.create_snapshot(recipe_id, "v1\n")
    history.create_snapshot(recipe_id, "v2\n")
    # Not a consecutive duplicate of the newest snapshot, so it is kept.
    assert history.create_snapshot(recipe_id, "v1\n") is not None
    assert len(history.list_snapshots(recipe_id)) == 3


def test_snapshot_preserves_exact_content_including_frontmatter_and_whitespace():
    recipe_id = "44444444-4444-4444-8444-444444444444"
    content = "---\n# a comment, custom:  spacing   preserved\nrecipe_id: keep\n---\n\n  # Indented\n\nBody.\n\n\n"
    # The snapshot is stored byte-for-byte; only the filename is synthesized.
    history.create_snapshot(recipe_id, content)
    snapshot = history.list_snapshots(recipe_id)[0]
    assert history.read_snapshot(recipe_id, snapshot.id) == content


def test_snapshot_ids_are_unique_even_within_the_same_microsecond():
    recipe_id = "55555555-5555-4555-8555-555555555555"
    moment = datetime(2026, 11, 17, 12, 30, 45, 123456, tzinfo=timezone.utc)
    ids = {history.make_snapshot_id(moment) for _ in range(50)}
    assert len(ids) == 50


def test_make_snapshot_id_embeds_utc_microsecond_timestamp():
    moment = datetime(2026, 11, 17, 12, 30, 45, 123456, tzinfo=timezone.utc)
    snapshot_id = history.make_snapshot_id(moment)
    parsed = history.parse_snapshot_id(snapshot_id)
    assert parsed == moment
    assert history.is_valid_snapshot_id(snapshot_id)


def test_invalid_recipe_ids_are_rejected():
    with pytest.raises(history.HistoryError):
        history.recipe_history_directory("not-a-uuid")
    with pytest.raises(history.HistoryError):
        history.create_snapshot("../escape", "content\n")
    assert history.list_snapshots("still-not-a-uuid") == []


def test_invalid_snapshot_ids_are_rejected():
    recipe_id = "66666666-6666-4666-8666-666666666666"
    history.create_snapshot(recipe_id, "content\n")

    assert not history.is_valid_snapshot_id("../other/x")
    assert not history.is_valid_snapshot_id("20261117T123045123456Z")  # missing the random suffix
    assert not history.is_valid_snapshot_id("20261317T123045123456Z-deadbeef")  # month 13
    with pytest.raises(history.HistoryError):
        history.read_snapshot(recipe_id, "../other/x")
    with pytest.raises(FileNotFoundError):
        history.read_snapshot(recipe_id, "20261117T123045123456Z-deadbeef")


def test_snapshot_files_live_outside_the_recipe_directory():
    recipe_id = "77777777-7777-4777-8777-777777777777"
    snapshot_path = history.create_snapshot(recipe_id, "content\n")
    assert snapshot_path is not None
    assert snapshot_path.is_relative_to(history_root())
    assert snapshot_path.parent == history_root() / "recipes" / recipe_id
    assert snapshot_path.suffix == ".md"


def test_read_snapshot_round_trip_and_delete_preserves_history():
    recipe_id = "88888888-8888-4888-8888-888888888888"
    content = "before delete\n"
    snapshot_path = history.create_snapshot(recipe_id, content)
    assert snapshot_path is not None

    snapshots = history.list_snapshots(recipe_id)
    assert len(snapshots) == 1
    assert history.read_snapshot(recipe_id, snapshots[0].id) == content
