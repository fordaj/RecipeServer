"""Behavioural tests for the canonical library-path rules."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from recipeserver.recipe_paths import (
    MARKDOWN_FILE_SUFFIX,
    RECIPE_FILENAME,
    display_path,
    iter_recipe_files,
    resolve_recipe_file,
    resolve_recipe_folder,
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "recipes"
    (root / "Dinner").mkdir(parents=True)
    (root / RECIPE_FILENAME).write_text("# Root\n", encoding="utf-8")
    (root / "Dinner" / RECIPE_FILENAME).write_text("# Dinner\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("requested", [RECIPE_FILENAME, "Dinner/recipe.md", "./Dinner/./recipe.md"])
def test_resolve_recipe_file_accepts_library_relative_paths(source: Path, requested: str):
    assert resolve_recipe_file(source, requested).is_file()


def test_resolve_recipe_file_trims_surrounding_whitespace(source: Path):
    assert resolve_recipe_file(source, f"  {RECIPE_FILENAME}  ") == source / RECIPE_FILENAME


@pytest.mark.parametrize(
    ("requested", "message"),
    [
        ("", "Expected a recipe path"),
        (None, "Expected a recipe path"),
        (42, "Expected a recipe path"),
        ("bad\\recipe.md", "Invalid file path"),
        ("bad\x00.md", "Invalid file path"),
        ("../outside.md", "Path must stay inside the source directory"),
        ("/etc/passwd.md", "Path must stay inside the source directory"),
        ("notes.txt", "Only Markdown (.md) files can be edited"),
    ],
)
def test_resolve_recipe_file_rejects_unsafe_paths(source: Path, requested: object, message: str):
    with pytest.raises(ValueError, match=re.escape(message)):
        resolve_recipe_file(source, requested)


def test_resolve_recipe_file_read_action_keeps_read_wording(source: Path):
    with pytest.raises(ValueError, match="Only Markdown \\(\\.md\\) files can be read"):
        resolve_recipe_file(source, "notes.txt", action="read")


def test_resolve_recipe_file_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "recipes"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    try:
        (root / "escape.md").symlink_to(outside)
    except OSError as exc:  # Windows requires developer mode for symlinks.
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="Path must stay inside the source directory"):
        resolve_recipe_file(root, "escape.md")


def test_resolve_recipe_folder_accepts_root_and_nested_folders(source: Path):
    assert resolve_recipe_folder(source, "") == source.resolve()
    assert resolve_recipe_folder(source, "Dinner") == (source / "Dinner").resolve()
    assert resolve_recipe_folder(source, None) == source.resolve()


@pytest.mark.parametrize(
    ("requested", "message"),
    [
        ("bad\\folder", "Invalid folder path"),
        ("bad\x00", "Invalid folder path"),
        ("/absolute", "Folder path must stay inside the source directory"),
        ("a/../b", "Folder path must stay inside the source directory"),
        ("C:folder", "Folder path must stay inside the source directory"),
    ],
)
def test_resolve_recipe_folder_rejects_unsafe_paths(source: Path, requested: str, message: str):
    with pytest.raises(ValueError, match=message):
        resolve_recipe_folder(source, requested)


def test_iter_recipe_files_is_sorted_and_skips_symlinks(tmp_path: Path):
    root = tmp_path / "recipes"
    (root / "b").mkdir(parents=True)
    (root / "a").mkdir(parents=True)
    (root / "b" / RECIPE_FILENAME).write_text("# B\n", encoding="utf-8")
    (root / "a" / RECIPE_FILENAME).write_text("# A\n", encoding="utf-8")
    (root / "notes.md").write_text("# Not a recipe\n", encoding="utf-8")

    assert iter_recipe_files(root) == [root / "a" / RECIPE_FILENAME, root / "b" / RECIPE_FILENAME]
    assert iter_recipe_files(tmp_path / "missing") == []


def test_display_path_returns_library_relative_posix_path(source: Path):
    assert display_path(source, source / "Dinner" / RECIPE_FILENAME) == f"Dinner/{RECIPE_FILENAME}"


def test_constants_match_the_recipe_data_convention():
    assert RECIPE_FILENAME == "recipe.md"
    assert MARKDOWN_FILE_SUFFIX == ".md"
