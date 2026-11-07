from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import frontmatter
import pytest
from bs4 import BeautifulSoup
from types import SimpleNamespace

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.server import (
    RecipeRequestHandler,
    _apply_rating_override,
    _validate_bulk_fields,
    _validate_bulk_rating,
)


def _write_recipe(path: Path, metadata: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{metadata}---\n# Recipe\n\nBody.\n", encoding="utf-8")


@pytest.fixture()
def bulk_server(tmp_path):
    source = tmp_path / "source"
    _write_recipe(source / "Alpha" / "recipe.md", "contributor: Avery\ncategories:\n  - Old\nmeals:\n  - Dinner\nratings:\n  - name: Kim\n    rating: 5\n    id: r1\n    created: '2026-01-01T00:00:00Z'\n    updated: '2026-01-01T00:00:00Z'\n")
    _write_recipe(source / "Beta" / "recipe.md", "contributor: Blair\ncategories:\n  - Other\nmeals:\n  - Lunch\n")
    saved, deleted = [], []
    handler = partial(
        RecipeRequestHandler,
        directory=str(tmp_path),
        source_directory=source,
        on_markdown_saved=saved.append,
        on_recipes_deleted=deleted.extend,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", source, saved, deleted
    server.shutdown()
    server.server_close()
    thread.join()


def _post(url, payload):
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    return urlopen(request)


def test_apply_rating_override_replaces_same_name_and_adds_new(bulk_server):
    base = [{"name": "Kim", "rating": 5, "id": "r1", "created": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z"}]
    overridden = _apply_rating_override(base, "kim", 9)
    assert len(overridden) == 1 and overridden[0]["rating"] == 9 and overridden[0]["id"] == "r1"
    added = _apply_rating_override(base, "Andy", 7)
    assert len(added) == 2 and added[1]["name"] == "Andy" and added[1]["id"]


def test_validate_bulk_helpers_reject_bad_input():
    with pytest.raises(ValueError):
        _validate_bulk_fields(["updatedOn"])
    with pytest.raises(ValueError):
        _validate_bulk_rating({"name": "", "rating": 5})
    assert _validate_bulk_rating({"name": "Andy", "score": 8}) == ("Andy", 8)


def test_bulk_editor_get_returns_metadata_and_ratings(bulk_server):
    base, source, _, _ = bulk_server
    query = urlencode({"path": ["Alpha/recipe.md", "Beta/recipe.md"]}, doseq=True)
    with urlopen(f"{base}/api/bulk-editor?{query}") as response:
        data = json.loads(response.read())
    assert [r["path"] for r in data["recipes"]] == ["Alpha/recipe.md", "Beta/recipe.md"]
    assert data["recipes"][0]["metadata"]["contributor"] == "Avery"
    assert data["recipes"][0]["ratings"][0]["name"] == "Kim"


def test_bulk_edit_single_field_does_not_touch_others(bulk_server):
    base, source, saved, _ = bulk_server
    with _post(f"{base}/api/bulk-editor", {"paths": ["Alpha/recipe.md", "Beta/recipe.md"], "metadata": {"categories": ["Slow Cooker"]}, "fields": ["categories"]}) as response:
        assert json.loads(response.read())["count"] == 2
    alpha = frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata
    beta = frontmatter.loads((source / "Beta" / "recipe.md").read_text()).metadata
    assert alpha["categories"] == ["Slow Cooker"] and alpha["contributor"] == "Avery" and alpha["meals"] == ["Dinner"]
    assert beta["categories"] == ["Slow Cooker"] and beta["contributor"] == "Blair"
    assert len(saved) == 2


def test_bulk_edit_rating_merges_by_name(bulk_server):
    base, source, _, _ = bulk_server
    with _post(f"{base}/api/bulk-editor", {"paths": ["Alpha/recipe.md", "Beta/recipe.md"], "rating": {"name": "Kim", "rating": 9}}) as response:
        assert json.loads(response.read())["success"] is True
    alpha = frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata
    beta = frontmatter.loads((source / "Beta" / "recipe.md").read_text()).metadata
    assert alpha["ratings"][0]["rating"] == 9 and len(alpha["ratings"]) == 1
    assert beta["ratings"][0]["name"] == "Kim" and beta["ratings"][0]["rating"] == 9


def test_bulk_edit_prechecks_and_validates(bulk_server):
    base, source, _, _ = bulk_server
    with pytest.raises(HTTPError) as error:
        _post(f"{base}/api/bulk-editor", {"paths": ["Alpha/recipe.md", "Missing/recipe.md"], "metadata": {"categories": ["X"]}, "fields": ["categories"]})
    assert error.value.code == 404
    # Nothing written for Alpha either.
    assert frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata["categories"] == ["Old"]
    with pytest.raises(HTTPError) as error:
        _post(f"{base}/api/bulk-editor", {"paths": [], "metadata": {"categories": ["X"]}})
    assert error.value.code == 400


def test_bulk_delete_removes_files_and_notifies(bulk_server):
    base, source, _, deleted = bulk_server
    with _post(f"{base}/api/bulk-delete", {"paths": ["Alpha/recipe.md", "Beta/recipe.md"]}) as response:
        assert json.loads(response.read()) == {"success": True, "paths": ["Alpha/recipe.md", "Beta/recipe.md"], "count": 2}
    assert not (source / "Alpha" / "recipe.md").exists()
    assert not (source / "Beta" / "recipe.md").exists()
    assert len(deleted) == 2
    with pytest.raises(HTTPError) as error:
        _post(f"{base}/api/bulk-delete", {"paths": ["../outside.md"]})
    assert error.value.code == 400


def test_bulk_mixed_and_save_live_inside_field_labels_hidden_by_default():
    script = (
        Path(__file__).parents[1]
        / "src"
        / "recipeserver"
        / "assets"
        / "recipe-editor.js"
    ).read_text(encoding="UTF-8")
    css = (
        Path(__file__).parents[1]
        / "src"
        / "recipeserver"
        / "assets"
        / "recipe-editor.css"
    ).read_text(encoding="UTF-8")
    # Each metadata field label contains a hidden * MIXED span and a hidden Save button inside its input control.
    assert script.count('<span class="recipe-editor__mixed" hidden>* MIXED</span>') >= 12
    assert script.count('class="recipe-editor__bulk-field-save"') >= 12
    assert 'class="recipe-editor__field-control"' in script
    assert 'data-field="categories"' in script and 'data-field="source"' in script and 'data-field="rating"' in script
    # Old standalone bulk panel is gone.
    assert "Save Individual Fields" not in script
    assert "recipe-editor__bulk-field-actions" not in script
    # Mixed/save are toggled (unhidden) rather than created/removed.
    assert "badge.hidden = false" in script
    assert "button.hidden = !visible" in script
    assert 'dialog.classList.toggle(\'is-bulk\', visible)' in script or 'dialog.classList.toggle("is-bulk"' in script
    assert "setupBulkFieldButtons()" in script
    assert ".recipe-editor__mixed[hidden]" in css
    assert ".recipe-editor__bulk-field-save[hidden]" in css
    assert ".recipe-editor__field-control" in css


def test_index_renders_selection_mode_and_bulk_controls(tmp_path: Path):
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="UTF-8")
    (recipe_path.parent / "image.webp").write_bytes(b"img")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()
    soup = BeautifulSoup((tmp_path / "index.html").read_text(encoding="UTF-8"), "html.parser")
    assert soup.select_one("#bulk-selection-mode") is not None
    assert "Selection Mode" in soup.select_one(".bulk-selection-toggle").get_text()
    assert soup.select_one("#bulk-controls") is not None
    assert soup.select_one("#bulk-edit").get_text(strip=True) == "Bulk Edit"
    assert soup.select_one("#clear-selections").get_text(strip=True) == "Clear Selections"
    box = soup.select_one(".recipe-select__checkbox")
    assert box is not None and box["data-path"] == "soup/recipe.md"
    assert soup.select_one("#recipe-list .recipe")["data-path"] == "soup/recipe.md"
    # The checkbox sits inside the card so it can overlay the image (upper-left).
    assert box.find_parent("article", class_="recipe-card") is not None
