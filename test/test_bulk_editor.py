import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import frontmatter
import pytest

from recipeserver.server import RecipeRequestHandler, _validate_bulk_metadata, _validate_ratings


def valid_rating(name="Kailey Ford", rating=8.5, rating_id="rating-1"):
    return {
        "name": name,
        "created": "2026-10-27T01:38:21.996Z",
        "updated": "2026-10-27T01:38:21.996Z",
        "id": rating_id,
        "rating": rating,
    }


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


def start_server(source: Path, on_markdown_saved=None, on_recipes_deleted=None):
    saved_paths: list[Path] = []
    deleted: list[bool] = []

    def handle_recipes_deleted() -> None:
        deleted.append(True)

    handler = partial(
        RecipeRequestHandler,
        directory=str(source),
        source_directory=source,
        on_markdown_saved=on_markdown_saved if on_markdown_saved is not None else saved_paths.append,
        on_recipes_deleted=on_recipes_deleted if on_recipes_deleted is not None else handle_recipes_deleted,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    return server, thread, saved_paths, deleted


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join()


def write_recipe(directory: Path, title: str, meals: list[str], categories: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    recipe = directory / "recipe.md"
    recipe.write_text(
        f"""---
title: {title}
meals:
  - {meals[0]}
categories:
  - {categories[0]}
contributor: Avery
createdOn: "2024-06-15T12:30:00Z"
updatedOn: "2024-06-20T12:30:00Z"
---
# {title}

Body for {title}.
""",
        encoding="utf-8",
    )
    return recipe


def test_validate_bulk_metadata_accepts_partial_edits():
    assert _validate_bulk_metadata({"categories": ["Slow Cooker"]}) == {"categories": ["Slow Cooker"]}

    with pytest.raises(ValueError):
        _validate_bulk_metadata({"makes": "not-a-number"})


def test_bulk_endpoint_returns_metadata_for_each_recipe(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    write_recipe(source / "dinner", "Baked Ziti", ["Dinner"], ["Baking"])
    write_recipe(source / "soup", "Chicken Soup", ["Dinner"], ["Soup"])

    server, thread, _, _ = start_server(source)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(
            f"{base_url}/api/recipe-bulk?{urlencode({'paths': ['dinner/recipe.md', 'soup/recipe.md']}, doseq=True)}",
        )
        assert status == 200
        assert body["recipes"][0]["path"] == "dinner/recipe.md"
        assert body["recipes"][0]["metadata"]["meals"] == ["Dinner"]
        assert body["recipes"][0]["metadata"]["categories"] == ["Baking"]
        assert body["recipes"][1]["metadata"]["meals"] == ["Dinner"]
        assert body["recipes"][1]["metadata"]["categories"] == ["Soup"]
    finally:
        stop_server(server, thread)


def test_bulk_edit_saves_metadata_to_all_selected_recipes(tmp_path: Path):
    source = tmp_path / "recipes"
    dinner = write_recipe(source / "dinner", "Baked Ziti", ["Dinner"], ["Baking"])
    soup = write_recipe(source / "soup", "Chicken Soup", ["Dinner"], ["Soup"])

    saved_paths: list[Path] = []
    server, thread, _, _ = start_server(source, on_markdown_saved=saved_paths.append)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(f"{base_url}/api/recipe-bulk-edit", {
            "paths": ["dinner/recipe.md", "soup/recipe.md"],
            "metadata": {"categories": ["Slow Cooker"], "meals": ["Dinner"]},
        })
        assert status == 200
        assert body["success"] is True
        assert len(body["results"]) == 2
        assert all(item["success"] for item in body["results"])

        for recipe in (dinner, soup):
            post = frontmatter.loads(recipe.read_text(encoding="utf-8"))
            assert post.metadata["categories"] == ["Slow Cooker"]
            assert post.metadata["meals"] == ["Dinner"]
            assert post.metadata["contributor"] == "Avery"
            assert post.metadata["updatedOn"] != "2024-06-20T12:30:00Z"
        assert saved_paths == [dinner, soup]
    finally:
        stop_server(server, thread)


def test_bulk_edit_merges_ratings_by_name_and_keeps_others(tmp_path: Path):
    source = tmp_path / "recipes"
    dinner = source / "dinner"
    dinner.mkdir(parents=True)
    recipe = dinner / "recipe.md"
    recipe.write_text(
        """---
title: Baked Ziti
meals:
  - Dinner
ratings:
  - name: Avery
    rating: 8
    id: rating-1
    created: "2024-06-15T12:30:00Z"
    updated: "2024-06-15T12:30:00Z"
---
# Baked Ziti

Body.
""",
        encoding="utf-8",
    )

    saved_paths: list[Path] = []
    server, thread, _, _ = start_server(source, on_markdown_saved=saved_paths.append)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(f"{base_url}/api/recipe-bulk-edit", {
            "paths": ["dinner/recipe.md"],
            "metadata": {
                "ratings": [
                    {
                        "name": "Andy",
                        "rating": 5,
                        "id": "rating-2",
                        "created": "2026-10-27T01:38:21.996Z",
                        "updated": "2026-10-27T01:38:21.996Z",
                    }
                ]
            },
        })
        assert status == 200
        assert body["success"] is True

        post = frontmatter.loads(recipe.read_text(encoding="utf-8"))
        names = [rating["name"] for rating in post.metadata["ratings"]]
        assert names == ["Avery", "Andy"]
        andy = next(rating for rating in post.metadata["ratings"] if rating["name"] == "Andy")
        assert andy["rating"] == 5
    finally:
        stop_server(server, thread)


def test_bulk_edit_rejects_invalid_metadata_without_saving(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = write_recipe(source / "dinner", "Baked Ziti", ["Dinner"], ["Baking"])
    before = recipe.read_bytes()

    saved_paths: list[Path] = []
    server, thread, _, _ = start_server(source, on_markdown_saved=saved_paths.append)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(f"{base_url}/api/recipe-bulk-edit", {
            "paths": ["dinner/recipe.md"],
            "metadata": {"makes": "not-a-number"},
        })
        assert status == 400
        assert "makes" in body.get("error", "")
    finally:
        stop_server(server, thread)

    assert recipe.read_bytes() == before
    assert saved_paths == []


def test_bulk_delete_removes_selected_recipes_and_regenerates(tmp_path: Path):
    source = tmp_path / "recipes"
    dinner = write_recipe(source / "dinner", "Baked Ziti", ["Dinner"], ["Baking"])
    soup = write_recipe(source / "soup", "Chicken Soup", ["Dinner"], ["Soup"])
    kept = write_recipe(source / "kept", "Kept Recipe", ["Dinner"], ["Baking"])

    saved_paths: list[Path] = []
    server, thread, saved_paths_ref, deleted = start_server(
        source,
        on_markdown_saved=saved_paths.append,
        on_recipes_deleted=lambda: deleted.append(True),
    )
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(f"{base_url}/api/recipe-bulk-delete", {
            "paths": ["dinner/recipe.md", "soup/recipe.md"],
        })
        assert status == 200
        assert body["success"] is True
        assert len(body["results"]) == 2
        assert all(item["success"] for item in body["results"])
        assert not dinner.exists()
        assert not soup.exists()
        assert kept.exists()
        assert deleted == [True]
    finally:
        stop_server(server, thread)
