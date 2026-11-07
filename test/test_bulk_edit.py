from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import frontmatter
import pytest
from bs4 import BeautifulSoup

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.server import (
    RecipeRequestHandler,
    _apply_bulk_updates,
    _upsert_bulk_rating,
    _validate_bulk_paths,
    _validate_bulk_rating,
    _validate_bulk_updates,
)


def _start_server(tmp_path: Path, saved_paths: list, config_saved: list | None = None):
    handler = partial(
        RecipeRequestHandler,
        directory=str(tmp_path),
        source_directory=tmp_path,
        on_markdown_saved=saved_paths.append,
        on_config_saved=(lambda: config_saved.append(None) if config_saved is not None else None),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    return server, thread


def _post(url: str, payload: dict):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        return json.loads(response.read())


def test_validate_bulk_paths_rejects_bad_input():
    assert _validate_bulk_paths(["a/recipe.md"]) == ["a/recipe.md"]
    with pytest.raises(ValueError):
        _validate_bulk_paths([])
    with pytest.raises(ValueError):
        _validate_bulk_paths(["a/recipe.md", "a/recipe.md"])
    with pytest.raises(ValueError):
        _validate_bulk_paths(["a/recipe.md"] * 101)


def test_validate_bulk_updates_accepts_shared_fields_and_aliases():
    updates = _validate_bulk_updates(
        {
            "meals": ["Dinner"],
            "tags": ["Quick"],
            "cuisines": ["Thai"],
            "category": ["Soup"],
            "contributor": " Andy ",
            "createdOn": "2024-06-15",
            "author": "Jane Doe",
            "makes": 4,
            "difficulty": 3,
        }
    )
    assert updates["meals"] == ["Dinner"]
    assert updates["cuisine"] == ["Thai"]
    assert updates["categories"] == ["Soup"]
    assert updates["contributor"] == "Andy"
    assert updates["author"] == "Jane Doe"


def test_validate_bulk_updates_rejects_unknown_and_bad_types():
    with pytest.raises(ValueError):
        _validate_bulk_updates({"ingredients": ["x"]})
    with pytest.raises(ValueError):
        _validate_bulk_updates({"meals": "Dinner"})
    with pytest.raises(ValueError):
        _validate_bulk_updates({"makes": True})


def test_validate_bulk_rating():
    assert _validate_bulk_rating({"name": " Avery ", "rating": 8.5}) == {
        "name": "Avery",
        "rating": 8.5,
    }
    assert _validate_bulk_rating(None) is None
    with pytest.raises(ValueError):
        _validate_bulk_rating({"name": "Avery", "rating": 11})
    with pytest.raises(ValueError):
        _validate_bulk_rating({"name": "", "rating": 5})


def test_apply_bulk_updates_preserves_unlisted_fields_and_author():
    metadata = {
        "meals": ["Breakfast"],
        "contributor": "Old",
        "source": {"author": "Old Author", "title": "Book"},
        "title": "Keep me",
    }
    _apply_bulk_updates(metadata, {"meals": ["Dinner"], "author": "New Author"})
    assert metadata["meals"] == ["Dinner"]
    assert metadata["contributor"] == "Old"
    assert metadata["source"] == {"author": "New Author", "title": "Book"}
    assert metadata["title"] == "Keep me"


def test_upsert_bulk_rating_adds_and_updates():
    metadata = {"ratings": []}
    _upsert_bulk_rating(metadata, {"name": "Avery", "rating": 8})
    assert len(metadata["ratings"]) == 1
    first_id = metadata["ratings"][0]["id"]
    _upsert_bulk_rating(metadata, {"name": "avery", "rating": 9.5})
    assert len(metadata["ratings"]) == 1
    assert metadata["ratings"][0]["rating"] == 9.5
    assert metadata["ratings"][0]["id"] == first_id
    _upsert_bulk_rating(metadata, {"name": "Blair", "rating": 7})
    assert len(metadata["ratings"]) == 2


def test_bulk_edit_api_updates_multiple_recipes(tmp_path: Path):
    for slug in ("alpha", "beta"):
        folder = tmp_path / slug
        folder.mkdir()
        (folder / "recipe.md").write_text(
            "---\nmeals: [Breakfast]\ncontributor: Old\n---\n# Dish\n",
            encoding="utf-8",
        )
    saved_paths: list = []
    server, thread = _start_server(tmp_path, saved_paths)
    url = f"http://127.0.0.1:{server.server_port}/api/bulk-edit"
    try:
        result = _post(
            url,
            {
                "paths": ["alpha/recipe.md", "beta/recipe.md"],
                "updates": {"meals": ["Dinner"], "contributor": "Avery"},
                "rating": {"name": "Casey", "rating": 9},
            },
        )
        assert result["success"] is True
        for slug in ("alpha", "beta"):
            metadata = frontmatter.loads(
                (tmp_path / slug / "recipe.md").read_text(encoding="utf-8")
            ).metadata
            assert metadata["meals"] == ["Dinner"]
            assert metadata["contributor"] == "Avery"
            assert metadata["ratings"][0]["name"] == "Casey"
            assert metadata["ratings"][0]["rating"] == 9
            assert "updatedOn" in metadata
        assert {path.name for path in saved_paths} == {"recipe.md"}
        assert len(saved_paths) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_bulk_edit_api_rejects_empty_and_unknown(tmp_path: Path):
    saved_paths: list = []
    server, thread = _start_server(tmp_path, saved_paths)
    url = f"http://127.0.0.1:{server.server_port}/api/bulk-edit"
    try:
        with pytest.raises(HTTPError) as error:
            _post(url, {"paths": ["a/recipe.md"], "updates": {}})
        assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            _post(url, {"paths": ["a/recipe.md"], "updates": {"nope": "x"}})
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_bulk_edit_api_deletes_selected_recipes(tmp_path: Path):
    for slug in ("alpha", "beta"):
        folder = tmp_path / slug
        folder.mkdir()
        (folder / "recipe.md").write_text("# Dish\n", encoding="utf-8")
    saved_paths: list = []
    config_saved: list = []
    server, thread = _start_server(tmp_path, saved_paths, config_saved)
    url = f"http://127.0.0.1:{server.server_port}/api/bulk-edit"
    try:
        result = _post(url, {"paths": ["alpha/recipe.md"], "delete": True})
        assert result["success"] is True
        assert not (tmp_path / "alpha" / "recipe.md").exists()
        assert (tmp_path / "beta" / "recipe.md").exists()
        assert config_saved == [None]
        with pytest.raises(HTTPError) as error:
            _post(
                url,
                {
                    "paths": ["beta/recipe.md"],
                    "updates": {"meals": ["Dinner"]},
                    "delete": True,
                },
            )
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_index_includes_bulk_selection_and_editor_assets(tmp_path: Path):
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="UTF-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"meals": ["Dinner"]}, recipe_path))

    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(page, "html.parser")
    recipe = soup.select_one("#recipe-list .recipe")
    assert recipe is not None
    assert recipe["data-path"] == "soup/recipe.md"
    select = recipe.select_one(".recipe-select__input")
    assert select is not None
    assert soup.select_one("#select-all-recipes") is not None
    assert soup.select_one("#bulk-edit-open") is not None
    assert soup.select_one("#bulk-edit-open").has_attr("disabled")
    assert '<link rel="stylesheet" href="/assets/bulk-editor.css?v=' in page
    assert '<script src="/assets/bulk-editor.js?v=' in page

    bulk_js = (
        Path(__file__).parents[1]
        / "src"
        / "recipeserver"
        / "assets"
        / "bulk-editor.js"
    ).read_text(encoding="UTF-8")
    assert "/api/bulk-edit" in bulk_js
    assert "Delete selected recipes" in bulk_js
    index_js = (
        Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.js"
    ).read_text(encoding="UTF-8")
    assert ".recipe-select__input" in index_js
    assert "#select-all-recipes" in index_js
