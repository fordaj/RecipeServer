from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import frontmatter
import pytest

from recipeserver.server import (
    RecipeRequestHandler,
    _validate_bulk_metadata,
    _validate_bulk_rating,
)


def request_json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    if payload is None:
        request = Request(url, method="GET")
    else:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def start_server(source: Path):
    saved: list[list[Path]] = []
    deleted: list[list[Path]] = []

    def on_recipes_saved(paths):
        saved.append(list(paths))

    def on_recipes_deleted(paths):
        deleted.append(list(paths))

    handler = partial(
        RecipeRequestHandler,
        directory=str(source),
        source_directory=source,
        on_recipes_saved=on_recipes_saved,
        on_recipes_deleted=on_recipes_deleted,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    return server, thread, saved, deleted


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join()


def make_recipe(source: Path, name: str, front_matter: str) -> Path:
    folder = source / name
    folder.mkdir(parents=True)
    recipe = folder / "recipe.md"
    recipe.write_text(f"---\n{front_matter}---\n# {name}\n", encoding="utf-8")
    return recipe


def test_validate_bulk_metadata_accepts_partial_patch():
    assert _validate_bulk_metadata({"tags": ["Soup"], "contributor": "Andy"}) == {
        "tags": ["Soup"],
        "contributor": "Andy",
    }
    assert _validate_bulk_metadata({"tags": None}) == {"tags": None}


@pytest.mark.parametrize(
    "metadata",
    [
        {"makes": 3},
        {"difficulty": 5},
        {"updatedOn": "2024-01-01T00:00:00Z"},
        {"unknown": "x"},
        {"tags": "Soup"},
        {"source": {"unknown": "x"}},
    ],
)
def test_validate_bulk_metadata_rejects_invalid(metadata):
    with pytest.raises(ValueError):
        _validate_bulk_metadata(metadata)


def test_validate_bulk_rating():
    assert _validate_bulk_rating({"name": " Andy ", "rating": 8.5}) == {"name": "Andy", "rating": 8.5}
    assert _validate_bulk_rating(None) is None
    for bad in [{"name": "", "rating": 5}, {"name": "Andy", "rating": True}, {"name": "Andy", "rating": 11}]:
        with pytest.raises(ValueError):
            _validate_bulk_rating(bad)


def test_bulk_editor_sets_and_clears_fields_across_recipes(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    make_recipe(source, "soup", "meals:\n- Dinner\ntags:\n- Soup\ncontributor: Andy\n")
    make_recipe(source, "cake", "meals:\n- Dessert\ntags:\n- Cake\n")

    server, thread, saved, _ = start_server(source)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(
            f"{base_url}/api/bulk-editor",
            {
                "paths": ["soup/recipe.md", "cake/recipe.md"],
                "metadata": {
                    "meals": ["Lunch", "Dinner"],
                    "tags": None,
                    "contributor": "Jamie",
                },
            },
        )
        assert status == 200
        assert body["success"] is True
        assert body["updated"] == 2
        assert saved and len(saved[0]) == 2

        soup = frontmatter.loads((source / "soup" / "recipe.md").read_text(encoding="utf-8")).metadata
        cake = frontmatter.loads((source / "cake" / "recipe.md").read_text(encoding="utf-8")).metadata

        assert list(soup["meals"]) == ["Lunch", "Dinner"]
        assert list(cake["meals"]) == ["Lunch", "Dinner"]
        assert "tags" not in soup
        assert "tags" not in cake
        assert soup["contributor"] == "Jamie"
        assert cake["contributor"] == "Jamie"
        # Metadata edits bump updatedOn.
        assert soup.get("updatedOn")
        assert cake.get("updatedOn")
    finally:
        stop_server(server, thread)


def test_bulk_editor_applies_granular_source_patch(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    make_recipe(source, "soup", 'source:\n  title: Old Book\n  author: Someone\n  format: Book\n  url: ""\n')
    make_recipe(source, "cake", "meals:\n- Dessert\n")

    server, thread, _, _ = start_server(source)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(
            f"{base_url}/api/bulk-editor",
            {
                "paths": ["soup/recipe.md", "cake/recipe.md"],
                "metadata": {"source": {"author": "Andy Ford", "title": None}},
            },
        )
        assert status == 200
        assert body["success"] is True

        soup = frontmatter.loads((source / "soup" / "recipe.md").read_text(encoding="utf-8")).metadata
        assert soup["source"]["author"] == "Andy Ford"
        # Untouched keys are preserved.
        assert soup["source"]["format"] == "Book"
        assert "title" not in soup["source"]

        cake = frontmatter.loads((source / "cake" / "recipe.md").read_text(encoding="utf-8")).metadata
        assert cake["source"]["author"] == "Andy Ford"
    finally:
        stop_server(server, thread)


def test_bulk_editor_adds_and_overrides_named_rating(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    make_recipe(
        source,
        "soup",
        "ratings:\n- name: Andy\n  rating: 5\n  created: '2024-01-01T00:00:00Z'\n  updated: '2024-01-01T00:00:00Z'\n  id: old-id\n- name: Jamie\n  rating: 7\n  created: '2024-01-02T00:00:00Z'\n  updated: '2024-01-02T00:00:00Z'\n  id: jamie-id\n",
    )
    make_recipe(source, "cake", "meals:\n- Dessert\n")

    server, thread, _, _ = start_server(source)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(
            f"{base_url}/api/bulk-editor",
            {
                "paths": ["soup/recipe.md", "cake/recipe.md"],
                "rating": {"name": "Andy", "rating": 9},
            },
        )
        assert status == 200
        assert body["success"] is True

        soup = frontmatter.loads((source / "soup" / "recipe.md").read_text(encoding="utf-8")).metadata
        ratings = soup["ratings"]
        by_name = {entry["name"]: entry for entry in ratings}
        assert by_name["Andy"]["rating"] == 9
        # Override preserves created timestamp and id.
        assert by_name["Andy"]["created"] == "2024-01-01T00:00:00Z"
        assert by_name["Andy"]["id"] == "old-id"
        assert by_name["Jamie"]["rating"] == 7
        # Exactly one entry per name.
        assert [entry["name"].casefold() for entry in ratings].count("andy") == 1

        cake = frontmatter.loads((source / "cake" / "recipe.md").read_text(encoding="utf-8")).metadata
        assert cake["ratings"][0]["name"] == "Andy"
        assert cake["ratings"][0]["rating"] == 9

        # Ratings-only edits do not bump updatedOn.
        assert "updatedOn" not in cake
    finally:
        stop_server(server, thread)


def test_bulk_editor_rejects_invalid_payload_and_paths(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    make_recipe(source, "soup", "meals:\n- Dinner\n")

    server, thread, _, _ = start_server(source)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        # Unknown field
        status, _ = request_json(
            f"{base_url}/api/bulk-editor",
            {"paths": ["soup/recipe.md"], "metadata": {"makes": 2}},
        )
        assert status == 400

        # Nothing to apply
        status, _ = request_json(f"{base_url}/api/bulk-editor", {"paths": ["soup/recipe.md"]})
        assert status == 400

        # Path escapes the source directory
        status, _ = request_json(
            f"{base_url}/api/bulk-editor",
            {"paths": ["../outside.md"], "metadata": {"tags": ["x"]}},
        )
        assert status == 400

        # Missing file is reported per path, not as a panic
        status, body = request_json(
            f"{base_url}/api/bulk-editor",
            {"paths": ["missing/recipe.md"], "metadata": {"tags": ["x"]}},
        )
        assert status == 500
        assert body["updated"] == 0
        assert body["failed"][0]["path"] == "missing/recipe.md"
    finally:
        stop_server(server, thread)


def test_bulk_delete_removes_recipes_and_empty_directories(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    make_recipe(source, "soup", "meals:\n- Dinner\n")
    image_recipe = make_recipe(source, "cake", "meals:\n- Dessert\n")
    (image_recipe.parent / "photo.png").write_bytes(b"not a real png")

    server, thread, _, deleted = start_server(source)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(
            f"{base_url}/api/bulk-delete",
            {"paths": ["soup/recipe.md", "cake/recipe.md"]},
        )
        assert status == 200
        assert body["deleted"] == 2

        # Soup's directory was empty and is removed; cake's keeps its image.
        assert not (source / "soup").exists()
        assert (source / "cake").is_dir()
        assert not (source / "cake" / "recipe.md").exists()
        assert deleted and len(deleted[0]) == 2
    finally:
        stop_server(server, thread)
